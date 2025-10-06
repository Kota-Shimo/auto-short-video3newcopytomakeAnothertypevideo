#!/usr/bin/env python
"""
main.py – GPT で会話 → OpenAI TTS → 「lines.json & full.mp3」を作成し、
          chunk_builder.py で動画生成 → upload_youtube.py でアップロード。
          combos.yaml の各エントリを順に処理して、複数動画をアップロードできる。

Shorts 最適化版:
- 縦 1080x1920 向け
- 60 秒以内に自動トリム
- サムネイルは第二字幕言語を優先（表示されない場合あり）
- 多言語／マルチアカウント出力（combos.yaml）
"""

import argparse
import json
import logging
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from shutil import rmtree

import yaml
from openai import OpenAI
from pydub import AudioSegment

from config         import BASE, OUTPUT, TEMP
from dialogue       import make_dialogue        # (topic_str, audio_lang, turns, seed_phrase) -> list[(speaker, line)]
from translate      import translate            # translate(text, target_lang) -> str
from tts_openai     import speak                # speak(audio_lang, speaker, text, out_path)
from audio_fx       import enhance              # enhance(in_mp3, out_mp3)
from bg_image       import fetch as fetch_bg    # fetch_bg(topic, out_png)
from thumbnail      import make_thumbnail       # make_thumbnail(topic, title_lang, out_jpg)
from upload_youtube import upload               # upload(video_path, title, desc, tags, privacy, account, thumbnail, default_lang)

# -------------------------
# 基本設定
# -------------------------

GPT = OpenAI()
MAX_SHORTS_SEC = 59.0   # Shorts 安全上限

# combos.yaml 読み込み（音声×字幕×アカウントの「出力設定」）
with open(BASE / "combos.yaml", encoding="utf-8") as f:
    COMBOS = yaml.safe_load(f)["combos"]

LANG_NAME = {
    "en": "English", "pt": "Portuguese", "id": "Indonesian",
    "ja": "Japanese","ko": "Korean",     "es": "Spanish",
}

TOP_KEYWORDS = ["ホテル英語", "空港英会話", "レストラン英語", "仕事で使う英語", "旅行英会話", "接客英語"]

# -------------------------
# ユーティリティ
# -------------------------

def reset_temp():
    """一時ディレクトリを安全に作り直す。"""
    try:
        if TEMP.exists():
            rmtree(TEMP)
        TEMP.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logging.warning(f"[TEMP] reset failed (will retry clean): {e}")
        # 一部残骸があっても続行できるようにする
        TEMP.mkdir(parents=True, exist_ok=True)

def sanitize_title(raw: str) -> str:
    """タイトル文字列の前処理。"""
    if not raw:
        return "Auto Video"
    # 先頭の番号・箇条書き記号を除去
    title = re.sub(r"^\s*(?:\d+\s*[.)]|[-•・])\s*", "", raw)
    # 余分な空白を正規化
    title = re.sub(r"[\s\u3000]+", " ", title).strip()
    # 制限
    return title[:97] + "…" if len(title) > 100 else (title or "Auto Video")

def score_title(t: str) -> int:
    """日本語タイトル優先の簡易スコア。"""
    t = (t or "").strip()
    score = 0
    if any(t.startswith(k) for k in TOP_KEYWORDS): score += 20
    if re.search(r"\d+|チェックイン|注文|予約|例文|空港|ホテル|レストラン|面接|受付", t): score += 15
    score += max(0, 15 - max(0, len(t) - 28))
    if re.search(r"(英語|English)", t): score += 10
    return score

def _gpt(messages, model="gpt-4o-mini", temperature=0.7, max_tries=3, sleep_sec=1.2) -> str:
    """Chat Completions の簡易リトライラッパ（文字列返し）。"""
    last_err = None
    for i in range(max_tries):
        try:
            rsp = GPT.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
            )
            content = rsp.choices[0].message.content or ""
            return content.strip()
        except Exception as e:
            last_err = e
            logging.warning(f"[GPT] retry {i+1}/{max_tries} due to: {e}")
            time.sleep(sleep_sec)
    logging.error(f"[GPT] failed after retries: {last_err}")
    return ""

def _make_seed_phrase(topic: str, lang_code: str) -> str:
    """冒頭で自然に導入する一言（≤ 12 words）を取得（失敗時はフォールバック）。"""
    lang = LANG_NAME.get(lang_code, "English")
    prompt = (
        f"Write one very short opening sentence in {lang} "
        f"to introduce a language-learning roleplay scene about: {topic}.\n"
        "It should sound natural and motivating, ≤12 words.\n"
        "Examples: 'Let’s practice a hotel check-in.' / 'Time to learn how to order food.'"
    )
    text = _gpt([{"role":"user","content":prompt}], temperature=0.6)
    if not text:
        # フォールバック（言語に寄せるのが理想だが、最低限英語/日本語で成立）
        return "Let’s practice it." if lang_code != "ja" else "さっそく練習してみよう。"
    # 一行化＆過長カット
    text = sanitize_title(text).replace("\n", " ")
    return text[:80]

def _concat_trim_to(mp_paths, max_sec):
    """mp3 を連結して max_sec で打ち切り。各チャンクの実長さ(秒)を返す。"""
    max_ms = int(max_sec * 1000)
    combined = AudioSegment.silent(duration=0)
    new_durs, elapsed = [], 0
    for p in mp_paths:
        seg = AudioSegment.from_file(p)
        seg_ms = len(seg)
        if elapsed + seg_ms <= max_ms:
            combined += seg
            new_durs.append(seg_ms/1000)
            elapsed += seg_ms
        else:
            remain = max_ms - elapsed
            if remain > 0:
                combined += seg[:remain]
                new_durs.append(remain/1000)
            break
    # 保存
    try:
        (TEMP/"full_raw.mp3").unlink(missing_ok=True)
    except Exception:
        pass
    combined.export(TEMP/"full_raw.mp3", format="mp3")
    return new_durs

# 翻訳キャッシュ（text, lang） -> translated_text
_TRANSL_CACHE = {}

def _tr(text: str, lang: str) -> str:
    """重複翻訳の節約用キャッシュ。"""
    key = (text, lang)
    if key in _TRANSL_CACHE:
        return _TRANSL_CACHE[key]
    out = translate(text, lang) if lang else text
    _TRANSL_CACHE[key] = out
    return out

def _pick_title_lang(subs, audio_lang):
    """サムネ/タイトル用言語の安全な選択。"""
    if isinstance(subs, list) and len(subs) >= 2:
        # 第二字幕言語を優先
        return subs[1]
    return audio_lang or "en"

def _safe_hashtags(lang_code: str) -> str:
    """言語別の保険用ハッシュタグ（GPT失敗時のフォールバック）。"""
    if lang_code == "ja":
        return "#英語学習 #英会話 #Shorts"
    return "#English #LanguageLearning #Shorts"

def make_title(topic, title_lang: str):
    """GPTベースのタイトル生成＋フォールバック付き。"""
    lang_label = LANG_NAME.get(title_lang, "English")

    if title_lang == "ja":
        prompt = (
            "You are a YouTube copywriter.\n"
            "Generate 5 concise Japanese titles (each ≤28 JP chars) for a LANGUAGE-LEARNING video.\n"
            "Each title must start with a strong scenario keyword and include a benefit.\n"
            f"Scenario/topic: {topic}\n"
            "Return 5 lines only."
        )
        raw = _gpt([{"role":"user","content":prompt}], temperature=0.7)
        cands = [sanitize_title(x) for x in raw.split("\n") if x.strip()] if raw else []
        # 軽い補強（頭出し）
        cands = [t if any(t.startswith(k) for k in TOP_KEYWORDS) else f"{topic} {t}" for t in cands]
        if not cands:
            # フォールバック
            cands = [f"{topic} を一瞬で覚える", f"{topic} いま使える英語", f"{topic} 45秒でマスター"]
        return sorted(cands, key=score_title, reverse=True)[0][:28]

    # 非日本語
    prompt = (
        f"You are a YouTube copywriter.\n"
        f"Generate 5 concise {lang_label} titles (each ≤55 chars).\n"
        "Each title should be clear and benefit-driven.\n"
        f"Topic: {topic}\n"
        "Return 5 lines only."
    )
    raw = _gpt([{"role":"user","content":prompt}], temperature=0.7)
    cands = [sanitize_title(x) for x in raw.split("\n") if x.strip()] if raw else []
    if not cands:
        cands = [f"{topic}: Learn it fast", f"{topic}: Real phrases", f"{topic}: Speak it today"]
    return max(cands, key=len)[:55]

def make_desc(topic, title_lang: str):
    """説明文＋ハッシュタグ（GPT失敗時はフォールバック）。"""
    lang_label = LANG_NAME.get(title_lang, "English")

    prompt_desc = (
        f"Write one sentence (≤90 chars) in {lang_label} "
        f"summarising \"{topic}\" and ending with a call-to-action."
    )
    base = _gpt([{"role":"user","content":prompt_desc}], temperature=0.5)
    if not base:
        base = (f"{topic} — learn and practice now!"
                if title_lang != "ja"
                else f"{topic} を今日から使おう！")

    prompt_tags = (
        f"List 2 or 3 popular hashtags in {lang_label} "
        "used by language learners. Only hashtags, space separated."
    )
    hashtags = _gpt([{"role":"user","content":prompt_tags}], temperature=0.3)
    if not hashtags or "#" not in hashtags:
        hashtags = _safe_hashtags(title_lang)

    return f"{base.strip()} {hashtags.strip()}"

def make_tags(topic, audio_lang, subs, title_lang):
    """タグ生成：言語/字幕に応じて拡張（最大15件）。"""
    tags = [
        topic, "language learning",
        f"{LANG_NAME.get(title_lang,'English')} study",
        f"{LANG_NAME.get(title_lang,'English')} practice",
    ]
    if title_lang == "ja":
        tags.extend(["英会話","旅行英会話","接客英語","仕事で使う英語"])
    # 追加字幕の言語をタグに
    for code in (subs[1:] if isinstance(subs, list) else []):
        if code in LANG_NAME:
            tags.extend([f"{LANG_NAME[code]} subtitles", f"Learn {LANG_NAME[code]}"])
    # 重複除去＆長さ制限
    return list(dict.fromkeys([t for t in tags if t]))[:15]

# -------------------------
# メイン処理
# -------------------------

def run_all(topic, turns, privacy, do_upload, chunk_size):
    """combos.yaml の各組合せを総当たりで生成。"""
    for combo in COMBOS:
        audio_lang  = combo.get("audio")
        subs        = combo.get("subs", [])
        account     = combo.get("account", "default")
        title_lang  = combo.get("title_lang") or _pick_title_lang(subs, audio_lang)

        if not audio_lang or not subs:
            logging.warning(f"[SKIP] invalid combo (audio/subs missing): {combo}")
            continue

        logging.info(
            f"=== Combo: audio={audio_lang}, subs={subs}, account={account}, title_lang={title_lang} ==="
        )
        try:
            run_one(topic, turns, audio_lang, subs, title_lang,
                    privacy, account, do_upload, chunk_size)
        except Exception as e:
            logging.exception(f"[ERROR] combo failed: {combo} :: {e}")

def run_one(topic, turns, audio_lang, subs, title_lang,
            yt_privacy, account, do_upload, chunk_size):
    """1コンボ（音声×字幕×アカウント）分を生成して投稿まで。"""
    reset_temp()

    # 1) 台本用トピックを音声言語へ（英語音声なら英語化等）
    topic_for_dialogue = _tr(topic, audio_lang) if audio_lang and audio_lang != "ja" else topic

    # 2) Seed Hook（失敗しても安全にフォールバック）
    seed_phrase = _make_seed_phrase(topic_for_dialogue, audio_lang or "en")

    # 3) 台本生成（dialogue モジュールの I/F はそのまま）
    dialogue = make_dialogue(topic_for_dialogue, audio_lang, turns, seed_phrase=seed_phrase)

    # 4) 音声（各セグメント）＋ 字幕の下準備
    mp_parts, sub_rows = [], [[] for _ in subs]
    valid_dialogue = []
    for i, (spk, line) in enumerate(dialogue, 1):
        line = (line or "").strip()
        if not line:
            continue
        mp = TEMP / f"{i:02d}.mp3"
        speak(audio_lang, spk, line, mp)  # TTS
        mp_parts.append(mp)
        valid_dialogue.append((spk, line))

        # 字幕：subs[0] が音声言語である前提のまま（異なる場合は translate）
        for r, lang in enumerate(subs):
            sub_rows[r].append(line if lang == audio_lang else _tr(line, lang))

    if not mp_parts:
        raise RuntimeError("No speech parts generated. Dialogue may be empty.")

    # 5) 60秒以内にトリム → 音処理（ノーマライズ等）
    new_durs = _concat_trim_to(mp_parts, MAX_SHORTS_SEC)
    enhance(TEMP / "full_raw.mp3", TEMP / "full.mp3")

    # 背景画像
    bg_png = TEMP / "bg.png"
    fetch_bg(topic, bg_png)

    # 対応する dialogue の長さに揃える（空行は除外済）
    valid_dialogue = valid_dialogue[:len(new_durs)]

    # 6) lines.json を保存（chunk_builder.py が参照）
    lines_data = []
    for i, ((spk, txt), dur) in enumerate(zip(valid_dialogue, new_durs), 1):
        row = [spk]
        for r in range(len(subs)):
            row.append(sub_rows[r][i-1])  # 同インデックスの字幕
        row.append(dur)
        lines_data.append(row)

    (TEMP / "lines.json").write_text(
        json.dumps(lines_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # lines だけ作って終了（デバッグ用）
    if args.lines_only:
        logging.info("[DONE] lines-only mode: lines.json created.")
        return

    # 7) サムネ生成（第2字幕言語優先）
    thumb = TEMP / "thumbnail.jpg"
    thumb_lang = _pick_title_lang(subs, audio_lang)
    make_thumbnail(topic, thumb_lang, thumb)

    # 8) chunk_builder を起動して映像合成
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_mp4 = OUTPUT / f"{audio_lang}-{'_'.join(subs)}_{stamp}.mp4"
    final_mp4.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "python", str(BASE / "chunk_builder.py"),
        str(TEMP / "lines.json"), str(TEMP / "full.mp3"), str(bg_png),
        "--chunk", str(chunk_size),
        "--rows", str(len(subs)),
        "--out", str(final_mp4),
    ]
    logging.info("🔹 chunk_builder cmd: %s", " ".join(cmd))
    subprocess.run(cmd, check=True)

    # 9) アップロード関連（タイトル/説明/タグ）
    title = make_title(topic, title_lang)
    desc  = make_desc(topic, title_lang)
    tags  = make_tags(topic, audio_lang, subs, title_lang)

    # メタ保存（検証・再投稿用）
    meta = {
        "topic": topic,
        "topic_for_dialogue": topic_for_dialogue,
        "audio_lang": audio_lang,
        "subs": subs,
        "account": account,
        "title_lang": title_lang,
        "title": title,
        "desc": desc,
        "tags": tags,
        "seed_phrase": seed_phrase,
        "stamp": stamp,
        "output": str(final_mp4),
    }
    (TEMP / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    if not do_upload:
        logging.info("[DONE] no-upload mode: video created at %s", final_mp4)
        return

    # 10) YouTube アップロード
    upload(
        video_path=final_mp4,
        title=title,
        desc=desc,
        tags=tags,
        privacy=yt_privacy,
        account=account,
        thumbnail=thumb,
        default_lang=audio_lang,
    )
    logging.info("[DONE] uploaded: %s", final_mp4)

# -------------------------
# エントリポイント
# -------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("topic", help="会話テーマ（日本語でも可）")
    ap.add_argument("--turns", type=int, default=8)
    ap.add_argument("--privacy", default="unlisted", choices=["public", "unlisted", "private"])
    ap.add_argument("--lines-only", action="store_true")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--chunk", type=int, default=9999, help="Shortsは分割せず1本推奨")
    args = ap.parse_args()

    run_all(args.topic, args.turns, args.privacy, not args.no_upload, args.chunk)
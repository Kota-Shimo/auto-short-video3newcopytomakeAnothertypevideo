#!/usr/bin/env python
"""
main.py – GPT で会話 → OpenAI TTS → 「lines.json & full.mp3」を作成し、
          chunk_builder.py で動画生成 → upload_youtube.py でアップロード。
          combos.yaml の各エントリを順に処理して、複数動画をアップロードできる。

Usage:
  python main.py "トピック" [--turns 8] [--fsize-top 65] [--fsize-bot 60]
                   [--privacy unlisted] [--lines-only] [--no-upload]
                   [--chunk 60]
"""

import argparse, logging, re, json, subprocess
from datetime import datetime
from pathlib import Path
from shutil import rmtree

import yaml
from pydub import AudioSegment
from openai import OpenAI

from config         import BASE, OUTPUT, TEMP
from dialogue       import make_dialogue
from translate      import translate
from tts_openai     import speak
from podcast        import concat_mp3
from bg_image       import fetch as fetch_bg
from audio_fx       import enhance
from thumbnail      import make_thumbnail
from upload_youtube import upload

GPT = OpenAI()

# combos.yaml 読み込み (各エントリ: audio, subs, account, title_lang)
with open(BASE / "combos.yaml", encoding="utf-8") as f:
    COMBOS = yaml.safe_load(f)["combos"]

def reset_temp():
    if TEMP.exists():
        rmtree(TEMP)
    TEMP.mkdir(exist_ok=True)

def sanitize_title(raw: str) -> str:
    title = re.sub(r"[\s\u3000]+", " ", raw).strip()
    return title[:97] + "…" if len(title) > 100 else title or "Auto Video"

def _primary_lang(audio_lang: str, subs: list[str]) -> str:
    """複数字幕がある場合に「メイン表示言語」を決める（互換用）"""
    return subs[1] if len(subs) > 1 else audio_lang

# ───────── タイトル最適化（複数案→自動スコアで採用） ─────────
TOP_KEYWORDS = ["ホテル英語", "空港英会話", "レストラン英語", "仕事で使う英語", "旅行英会話", "接客英語"]

def score_title(t: str) -> int:
    t = t.strip()
    score = 0
    if any(t.startswith(k) for k in TOP_KEYWORDS):
        score += 20
    if re.search(r"\d+|チェックイン|注文|予約|問い合わせ|例文|空港|ホテル|レストラン|面接|受付", t):
        score += 15
    score += max(0, 15 - max(0, len(t) - 28))
    if re.search(r"(英語|English)", t):
        score += 10
    return score

def make_title(topic, title_lang: str):
    if title_lang == "ja":
        prompt = (
            "You are a YouTube copywriter.\n"
            "Generate 5 concise Japanese titles (each ≤28 JP chars) for a LANGUAGE-LEARNING video.\n"
            "Each title must start with a strong scenario keyword and include a concrete benefit.\n"
            f"Scenario/topic: {topic}\n"
            "Return as 5 lines, one per title, no bullets."
        )
    else:
        prompt = (
            f"You are a YouTube copywriter.\n"
            f"Generate 5 concise {LANG_NAME.get(title_lang, 'English')} titles (each ≤55 chars) for a LANGUAGE-LEARNING video.\n"
            "Each title must start with a strong scenario keyword and include a concrete benefit.\n"
            f"Scenario/topic: {topic}\n"
            "Return as 5 lines, one per title, no bullets."
        )

    rsp = GPT.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    cands = [sanitize_title(x) for x in rsp.choices[0].message.content.split("\n") if x.strip()]
    # 日本語タイトルだけ TOP_KEYWORDS チェック適用
    if title_lang == "ja":
        cands = [t if any(t.startswith(k) for k in TOP_KEYWORDS) else f"{topic} {t}" for t in cands]
        best = sorted(cands, key=score_title, reverse=True)[0]
        return best[:28]
    else:
        best = max(cands, key=len)  # 55字上限で情報量が多いものを簡易採用
        return best[:55]

def make_desc(topic, title_lang: str):
    prompt_desc = (
        f"Write one sentence (≤90 characters) in {LANG_NAME.get(title_lang,'English')} summarising "
        f'\"{topic}\" and ending with a short call-to-action.'
    )
    rsp = GPT.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt_desc}],
        temperature=0.5,
    )
    base = rsp.choices[0].message.content.strip()

    prompt_tags = (
        f"List 2 or 3 popular hashtags in {LANG_NAME.get(title_lang,'English')} used by language learners studying {LANG_NAME.get(title_lang,'English')}. "
        "Respond ONLY with the hashtags, separated by spaces."
    )
    tag_rsp = GPT.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt_tags}],
        temperature=0.3,
    )
    hashtags = tag_rsp.choices[0].message.content.strip().replace("\n", " ")
    return f"{base} {hashtags}"

LANG_NAME = {
    "en": "English",
    "pt": "Portuguese",
    "id": "Indonesian",
    "ja": "Japanese",
    "ko": "Korean",
    "es": "Spanish",
}

# ───────── タグの長尺最適化 ─────────
def make_tags(topic, audio_lang, subs):
    tags = [
        topic,
        "language learning",
        "英会話",
        "旅行英会話",
        f"{LANG_NAME.get(audio_lang,'')} speaking",
        "ホテル 英語",
        "空港 英会話",
        "接客英語",
        "仕事で使う英語",
    ]
    for code in subs[1:]:
        if code in LANG_NAME:
            tags.extend([f"{LANG_NAME[code]} subtitles", f"Learn {LANG_NAME[code]}"])
    return list(dict.fromkeys(tags))[:15]

# ───────── 説明欄に章分け ─────────
def _mmss(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m:02}:{s:02}"

def make_chapters_by_duration(durations, target_sections=4):
    total = float(sum(durations)) if durations else 0.0
    if total <= 0:
        return ""
    step  = max(60.0, total / max(1, target_sections))
    out   = [f"{_mmss(0)} Intro"]
    t = 0.0
    while t + step < total:
        t += step
        out.append(f"{_mmss(t)} Section}")
    out.append(f"{_mmss(total)} Outro")
    return "\n".join(out)

def run_all(topic, turns, fsize_top, fsize_bot, privacy, do_upload, chunk_size):
    for combo in COMBOS:
        audio_lang  = combo["audio"]
        subs        = combo["subs"]
        account     = combo.get("account", "default")
        # ★ title_lang を combos から読み取り。なければ subs[1] → audio_lang にフォールバック
        title_lang  = combo.get("title_lang", subs[1] if len(subs) > 1 else audio_lang)

        logging.info(f"=== Combo: {audio_lang}, subs={subs}, account={account}, title_lang={title_lang} ===")
        run_one(topic, turns,
                audio_lang, subs, title_lang,
                fsize_top, fsize_bot,
                yt_privacy=privacy,
                account=account,
                do_upload=do_upload,
                chunk_size=chunk_size)

def run_one(topic, turns, audio_lang, subs, title_lang,
            fsize_top, fsize_bot,
            yt_privacy, account, do_upload,
            chunk_size):
    reset_temp()

    # ★ 台本用トピックは音声言語に合わせて翻訳（英語音声で日本語が混ざるのを防ぐ）
    topic_for_dialogue = translate(topic, audio_lang) if audio_lang != "ja" else topic

    # --- (A) 台本作り & 音声合成 ---
    dialogue = make_dialogue(topic_for_dialogue, audio_lang, turns)
    mp_parts, durations, sub_rows = [], [], [[] for _ in subs]

    for i, (spk, line) in enumerate(dialogue, 1):
        if line.strip() in ("...", ""):
            continue
        mp = TEMP / f"{i:02d}.mp3"
        speak(audio_lang, spk, line, mp)
        mp_parts.append(mp)
        durations.append(AudioSegment.from_file(mp).duration_seconds)

        # 翻訳 or 同一言語
        for r, lang in enumerate(subs):
            sub_rows[r].append(line if lang == audio_lang else translate(line, lang))

    concat_mp3(mp_parts, TEMP / "full_raw.mp3")
    enhance(TEMP / "full_raw.mp3", TEMP / "full.mp3")

    # 背景画像
    bg_png = TEMP / "bg.png"
    fetch_bg(topic, bg_png)

    # lines.json 出力用
    valid_dialogue = [d for d in dialogue if d[1].strip() not in ("...", "")]
    lines_data = []
    for i, ((spk, txt), dur) in enumerate(zip(valid_dialogue, durations)):
        row = [spk]
        for r in range(len(subs)):
            row.append(sub_rows[r][i])
        row.append(dur)
        lines_data.append(row)

    (TEMP / "lines.json").write_text(
        json.dumps(lines_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --lines-only ならここで終了
    if args.lines_only:
        return

    # --- (B) サムネ（常に字幕の第2言語を優先）
    thumb = TEMP / "thumbnail.jpg"
    thumb_lang = subs[1] if len(subs) > 1 else audio_lang
    make_thumbnail(topic, thumb_lang, thumb)

    # --- (C) chunk_builder.py で mp4 作成 ---
    stamp      = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_mp4  = OUTPUT / f"{audio_lang}-{'_'.join(subs)}_{stamp}.mp4"
    final_mp4.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "python", str(BASE / "chunk_builder.py"),
        str(TEMP / "lines.json"), str(TEMP / "full.mp3"), str(bg_png),
        "--chunk", str(chunk_size),
        "--rows", str(len(subs)),
        "--out", str(final_mp4)
    ]
    # fsize_top, fsize_bot を渡す
    if fsize_top is not None:
        cmd += ["--fsize-top", str(fsize_top)]
    if fsize_bot is not None:
        cmd += ["--fsize-bot", str(fsize_bot)]

    logging.info("🔹 chunk_builder cmd: %s", " ".join(cmd))
    subprocess.run(cmd, check=True)

    if not do_upload:
        logging.info("⏭  --no-upload 指定のためアップロードしません。")
        return

    # --- (D) タイトル/説明は combos の title_lang に合わせる ---
    title = make_title(topic, title_lang)
    desc_base = make_desc(topic, title_lang)
    chapters_text = make_chapters_by_duration(durations, target_sections=4)
    desc = (chapters_text + "\n\n" + desc_base) if chapters_text else desc_base

    # タグ（長尺最適化・現状のまま）
    tags  = make_tags(topic, audio_lang, subs)

    # --- (E) アップロード（動画言語は音声言語に設定）
    upload(
        video_path   = final_mp4,
        title        = title,
        desc         = desc,
        tags         = tags,
        privacy      = yt_privacy,
        account      = account,
        thumbnail    = thumb,
        default_lang = audio_lang
    )

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    ap = argparse.ArgumentParser()
    ap.add_argument("topic", help="会話テーマ")
    ap.add_argument("--turns", type=int, default=8, help="往復回数 (1=Alice+Bob)")
    ap.add_argument("--fsize-top", type=int, default=65, help="上段字幕フォントサイズ")
    ap.add_argument("--fsize-bot", type=int, default=60, help="下段字幕フォントサイズ")
    ap.add_argument("--privacy", default="unlisted", choices=["public", "unlisted", "private"])
    ap.add_argument("--lines-only", action="store_true",
                    help="音声と lines.json だけ出力し、後続処理（動画生成・アップロード）は行わない")
    ap.add_argument("--no-upload", action="store_true",
                    help="動画生成までは行うが、YouTube へはアップロードしない")
    ap.add_argument("--chunk", type=int, default=60,
                    help="chunk_builder.py で1チャンク何行に分割するか")
    args = ap.parse_args()

    run_all(
        topic       = args.topic,
        turns       = args.turns,
        fsize_top   = args.fsize_top,
        fsize_bot   = args.fsize_bot,
        privacy     = args.privacy,
        do_upload   =(not args.no_upload),
        chunk_size  = args.chunk
    )
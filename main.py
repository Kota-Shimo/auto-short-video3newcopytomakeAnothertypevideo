# ======================= main.py ==========================
#!/usr/bin/env python
"""
main.py – GPT で会話 → OpenAI TTS → 多段字幕付き動画
          combos.yaml の組み合わせごとに生成し、必要なら自動アップロード。
"""
from datetime import datetime
import argparse, logging, yaml, re
import json                     # ★ 追加
from pathlib import Path
from shutil import rmtree
from pydub import AudioSegment
from openai import OpenAI

from config          import BASE, OUTPUT, TEMP
from dialogue        import make_dialogue
from translate       import translate
from tts_openai      import speak
from podcast         import concat_mp3
from bg_image        import fetch as fetch_bg
from subtitle_video  import build_video
from upload_youtube  import upload
from audio_fx        import enhance
from thumbnail       import make_thumbnail

GPT = OpenAI()

# ── 言語コンボ読み込み ─────────────────────────────
with open(BASE / "combos.yaml", encoding="utf-8") as f:
    COMBOS = yaml.safe_load(f)["combos"]

# ── TEMP を毎回空に ───────────────────────────────
def reset_temp():
    if TEMP.exists(): rmtree(TEMP)
    TEMP.mkdir(exist_ok=True)

# ── タイトル整形 ───────────────────────────────────
def sanitize_title(raw: str) -> str:
    title = re.sub(r"[\s\u3000]+", " ", raw).strip()
    return title[:97] + "…" if len(title) > 100 else title or "Auto Short"

# ── 共通: プライマリ言語決定 ────────────────────────
def _primary_lang(audio_lang: str, subs: list[str]) -> str:
    return subs[1] if len(subs) > 1 else audio_lang

# ── GPT タイトル ──────────────────────────────────
def make_title(topic, audio_lang, subs):
    primary = _primary_lang(audio_lang, subs)
    prompt  = (
        "You are a YouTube video copywriter.\n"
        "Write a clear and engaging title (≤55 ASCII or 28 JP characters).\n"
        f"Main part in {primary.upper()}, then ' | ' and an English gloss.\n"
        f"Topic: {topic}"
    )
    rsp = GPT.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return sanitize_title(rsp.choices[0].message.content.strip())

# ── GPT 説明欄 ────────────────────────────────────
def make_desc(topic, audio_lang, subs):
    primary = _primary_lang(audio_lang, subs)

    # --- 本文を生成 ---
    prompt_desc = (
        f"Write one sentence (≤90 characters) in {primary.upper()} summarising "
        f'\"{topic}\" and ending with a short call-to-action.'
    )
    rsp = GPT.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt_desc}],
        temperature=0.5,
    )
    base = rsp.choices[0].message.content.strip()

    # --- ハッシュタグをその国の言語で生成 ---
    prompt_tags = (
        f"List 2 or 3 popular hashtags in {primary.upper()} used by language learners studying {primary.upper()}. "
        "Respond ONLY with the hashtags, separated by spaces."
    )
    tag_rsp = GPT.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt_tags}],
        temperature=0.3,
    )
    hashtags = tag_rsp.choices[0].message.content.strip().replace("\n", " ")

    return f"{base} {hashtags}"

# ── メタ tags ─────────────────────────────────────
LANG_NAME = {"en": "English","pt":"Portuguese","id":"Indonesian",
             "ja":"Japanese","ko":"Korean","es":"Spanish"}
def make_tags(topic, audio_lang, subs):
    tags = [topic, "language learning", "Shorts",
            f"{LANG_NAME.get(audio_lang,'')} speaking"]
    for code in subs[1:]:
        if code in LANG_NAME:
            tags.extend([f"{LANG_NAME[code]} subtitles", f"Learn {LANG_NAME[code]}"])
    return list(dict.fromkeys(tags))[:15]

# ── 全コンボ処理 ───────────────────────────────────
def run_all(topic, turns, fsize_top, fsize_bot, 
            privacy, do_upload, lines_only):          # ★ 追加
    for combo in COMBOS:
        run_one(topic, turns,
                combo["audio"], combo["subs"],
                fsize_top, fsize_bot,
                yt_privacy=privacy,
                account   =combo.get("account","default"),
                do_upload =do_upload,
                lines_only=lines_only)

# ── 単一コンボ処理 ─────────────────────────────────
def run_one(topic, turns, audio_lang, subs,
            fsize_top, fsize_bot,
            yt_privacy, account, 
            do_upload, lines_only): 

    reset_temp()

    # 1) 会話スクリプト
    dialogue = make_dialogue(topic, audio_lang, turns)

    # 2) TTS & 翻訳
    mp_parts, durations, sub_rows = [], [], [[] for _ in subs]
    for i, (spk, line) in enumerate(dialogue, 1):
        if line.strip() in ("...", ""):
            print(f"⚠️ スキップ: {spk} のセリフが無効（{line}）")
            continue  # 音声も字幕も生成しない

        mp = TEMP / f"{i:02d}.mp3"
        speak(audio_lang, spk, line, mp)
        mp_parts.append(mp)
        durations.append(AudioSegment.from_file(mp).duration_seconds)
        for r, lang in enumerate(subs):
            sub_rows[r].append(line if lang == audio_lang else translate(line, lang))

    concat_mp3(mp_parts, TEMP / "full_raw.mp3")
    enhance(TEMP / "full_raw.mp3", TEMP / "full.mp3")

        # -------- lines.json を書き出して終了するモード --------
    if getattr(args, "lines_only", False):
        # dialogue から「しゃべった行」だけを再構築
        valid = [
            {
                "speaker": spk,
                "text": line.strip(),
                "duration": dur
            }
            for (spk, line), dur in zip(dialogue, durations)
            if line.strip() not in ("...", "")
        ]
        with open(TEMP / "lines.json", "w", encoding="utf-8") as f:
            json.dump(valid, f, ensure_ascii=False, indent=2)
        logging.info("📝 lines.json exported (%d lines) –– end.", len(valid))
        return 

    # 3) 背景画像
    bg_png = TEMP / "bg.png"; fetch_bg(topic, bg_png)

    # 3.5) サムネイル
    primary_lang = _primary_lang(audio_lang, subs)
    thumb = TEMP / "thumbnail.jpg"
    make_thumbnail(topic, primary_lang, thumb)

    # 4) 動画生成
    stamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    outfile = OUTPUT / f"{audio_lang}-{'_'.join(subs)}_{stamp}.mp4"
    # 有効な行だけで再構築（durationsとsub_rowsの長さに基づく）
    valid_dialogue = [d for d in dialogue if d[1].strip() not in ("...", "")]
    lines = [(spk, *[row[i] for row in sub_rows], dur)
            for i, ((spk, _), dur) in enumerate(zip(valid_dialogue, durations))]
    
    build_video(lines, bg_png, TEMP / "full.mp3", outfile,
                rows=len(subs),
                fsize_top=fsize_top,
                fsize_bot=fsize_bot)
    logging.info("✅ Video saved: %s", outfile.name)

    if not do_upload:
        logging.info("⏭️  --no-upload 指定のためアップロードをスキップ")
        return

    # 5) メタ & アップロード
    title = make_title(topic, audio_lang, subs)
    desc  = make_desc(topic, audio_lang, subs)
    tags  = make_tags(topic, audio_lang, subs)
    upload(outfile, title=title, desc=desc, tags=tags,
           privacy=yt_privacy, account=account,
           thumbnail=thumb)

# ── CLI ───────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("topic",               help="会話テーマ")
    ap.add_argument("--turns", type=int,   default=8, help="往復回数 (1=Alice+Bob)")
    ap.add_argument("--fsize-top", type=int, default=65, help="上段字幕フォントサイズ")
    ap.add_argument("--fsize-bot", type=int, default=60, help="下段字幕フォントサイズ")
    ap.add_argument("--privacy", default="unlisted",
                    choices=["public", "unlisted", "private"])
    ap.add_argument("--lines-only", action="store_true",
                    help="音声と lines.json だけ出力し、動画もアップロードも行わない")
    ap.add_argument("--no-upload", action="store_true",
                    help="動画生成のみ (YouTube へはアップしない)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    run_all(args.topic, turns=args.turns,
            fsize_top=args.fsize_top, fsize_bot=args.fsize_bot,
            privacy=args.privacy,
            do_upload=(not args.no_upload) and (not args.lines_only),
            lines_only=args.lines_only)          # ★ 追加

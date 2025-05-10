# ======================= main.py ==========================
#!/usr/bin/env python
"""
main.py – GPT で会話 → OpenAI TTS → 多段字幕付き動画
          combos.yaml の組み合わせごとに生成し、必要なら自動アップロード。
"""
from datetime import datetime
import argparse, logging, yaml, re
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
        "You are a YouTube Shorts copywriter.\n"
        "Write a catchy title (≤55 ASCII or 28 JP chars).\n"
        f"Main part in {primary.upper()}, then ' | ' and an English gloss, end with #Shorts.\n"
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
    prompt = (
        f"Write one sentence (≤90 characters) in {primary.upper()} summarising "
        f'\"{topic}\" and ending with a short call-to-action.'
    )
    rsp = GPT.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
    )
    base = rsp.choices[0].message.content.strip()
    hashtags = ["#Shorts", "#LanguageLearning"]
    if primary != "en": hashtags.append(f"#Learn{primary.upper()}")
    return f"{base} {' '.join(hashtags[:3])}"

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
def run_all(topic, turns, fsize_top, fsize_bot, privacy, do_upload):
    for combo in COMBOS:
        run_one(topic, turns,
                combo["audio"], combo["subs"],
                fsize_top, fsize_bot,
                yt_privacy=privacy,
                account   =combo.get("account","default"),
                do_upload =do_upload)

# ── 単一コンボ処理 ─────────────────────────────────
def run_one(topic, turns, audio_lang, subs,
            fsize_top, fsize_bot,
            yt_privacy, account, do_upload):

    reset_temp()

    # 1) 会話スクリプト
    dialogue = make_dialogue(topic, audio_lang, turns)

    # 2) TTS & 翻訳
    mp_parts, durations, sub_rows = [], [], [[] for _ in subs]
    for i, (spk, line) in enumerate(dialogue, 1):
        mp = TEMP / f"{i:02d}.mp3"
        speak(audio_lang, spk, line, mp)
        mp_parts.append(mp)
        durations.append(AudioSegment.from_file(mp).duration_seconds)
        for r, lang in enumerate(subs):
            sub_rows[r].append(line if lang == audio_lang else translate(line, lang))

    concat_mp3(mp_parts, TEMP / "full_raw.mp3")
    enhance(TEMP / "full_raw.mp3", TEMP / "full.mp3")

    # 3) 背景画像
    bg_png = TEMP / "bg.png"; fetch_bg(topic, bg_png)

    # 3.5) サムネイル
    primary_lang = _primary_lang(audio_lang, subs)
    thumb = TEMP / "thumbnail.jpg"
    make_thumbnail(topic, primary_lang, thumb)

    # 4) 動画生成
    stamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    outfile = OUTPUT / f"{audio_lang}-{'_'.join(subs)}_{stamp}.mp4"
    lines   = [(spk, *[row[i] for row in sub_rows], dur)
               for i, ((spk, _), dur) in enumerate(zip(dialogue, durations))]
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
    ap.add_argument("--fsize-top", type=int, default=48, help="上段字幕フォントサイズ")
    ap.add_argument("--fsize-bot", type=int, default=42, help="下段字幕フォントサイズ")
    ap.add_argument("--privacy", default="unlisted",
                    choices=["public", "unlisted", "private"])
    ap.add_argument("--no-upload", action="store_true",
                    help="動画生成のみ (YouTube へはアップしない)")
    args = ap.parse_args()

    run_all(args.topic, turns=args.turns,
            fsize_top=args.fsize_top, fsize_bot=args.fsize_bot,
            privacy=args.privacy, do_upload=(not args.no_upload))
# =========================================================

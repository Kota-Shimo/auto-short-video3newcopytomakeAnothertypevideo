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

# combos.yaml 読み込み (各エントリ: audio, subs, account)
with open(BASE / "combos.yaml", encoding="utf-8") as f:
    COMBOS = yaml.safe_load(f)["combos"]

def reset_temp():
    if TEMP.exists():
        rmtree(TEMP)
    TEMP.mkdir(exist_ok=True)

def sanitize_title(raw: str) -> str:
    title = re.sub(r"[\s\u3000]+", " ", raw).strip()
    return title[:97] + "…" if len(title) > 100 else title or "Auto Short"

def _primary_lang(audio_lang: str, subs: list[str]) -> str:
    """複数字幕がある場合に「メイン表示言語」を決める"""
    return subs[1] if len(subs) > 1 else audio_lang

def make_title(topic, audio_lang, subs):
    primary = _primary_lang(audio_lang, subs)
    prompt = (
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

def make_desc(topic, audio_lang, subs):
    primary = _primary_lang(audio_lang, subs)
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

LANG_NAME = {
    "en": "English",
    "pt": "Portuguese",
    "id": "Indonesian",
    "ja": "Japanese",
    "ko": "Korean",
    "es": "Spanish",
}
def make_tags(topic, audio_lang, subs):
    tags = [topic, "language learning", "Shorts",
            f"{LANG_NAME.get(audio_lang,'')} speaking"]
    for code in subs[1:]:
        if code in LANG_NAME:
            tags.extend([f"{LANG_NAME[code]} subtitles", f"Learn {LANG_NAME[code]}"])
    return list(dict.fromkeys(tags))[:15]

def run_all(topic, turns, fsize_top, fsize_bot, privacy, do_upload, chunk_size):
    """
    combos.yaml の全エントリをループし、
    1) lines.json & full.mp3 生成
    2) chunk_builder.py で動画化
    3) upload_youtube.py でアップロード
    """
    for combo in COMBOS:
        audio_lang = combo["audio"]
        subs       = combo["subs"]
        account    = combo.get("account", "default")

        print(f"=== Combo: {audio_lang}, subs={subs}, account={account} ===")
        run_one(topic, turns,
                audio_lang, subs,
                fsize_top, fsize_bot,
                yt_privacy=privacy,
                account=account,
                do_upload=do_upload,
                chunk_size=chunk_size)

def run_one(topic, turns, audio_lang, subs,
            fsize_top, fsize_bot,
            yt_privacy, account, do_upload,
            chunk_size):
    """
    1) GPTスクリプト + TTS で lines.json, full.mp3 を生成
    2) chunk_builder.py で チャンク動画作成
    3) upload_youtube.py でアップロード
    """
    reset_temp()

    # --- (A) 台本作り & 音声合成 ---
    dialogue = make_dialogue(topic, audio_lang, turns)
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

    # --- (B) サムネ（動画に直接は使わないがupload時に使うかも）
    primary_lang = _primary_lang(audio_lang, subs)
    thumb = TEMP / "thumbnail.jpg"
    make_thumbnail(topic, primary_lang, thumb)

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
    # fsize_top, fsize_bot を渡したい場合:
    if fsize_top is not None:
        cmd += ["--fsize-top", str(fsize_top)]
    if fsize_bot is not None:
        cmd += ["--fsize-bot", str(fsize_bot)]

    print("🔹 chunk_builder cmd:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    if not do_upload:
        print("⏭  --no-upload 指定のためアップロードしません。")
        return

    # --- (D) upload_youtube.py でアップロード ---
    title = make_title(topic, audio_lang, subs)
    desc  = make_desc(topic, audio_lang, subs)
    tags  = make_tags(topic, audio_lang, subs)

    upload(
        video_path = final_mp4,
        title      = title,
        desc       = desc,
        tags       = tags,
        privacy    = yt_privacy,
        account    = account,
        thumbnail  = thumb
    )


if __name__ == "__main__":
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
#!/usr/bin/env python
"""
main.py – GPT で会話 → OpenAI TTS → 「lines.json & full.mp3」を作成し、
          chunk_builder.py で動画生成 → upload_youtube.py でアップロード。
          combos.yaml の各エントリを順に処理して、複数動画をアップロードできる。

Shorts 最適化版:
- 縦 1080x1920 向け
- 60 秒以内に自動トリム
- サムネイルは第二字幕言語を優先（表示されない場合あり）
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
from audio_fx       import enhance
from bg_image       import fetch as fetch_bg
from thumbnail      import make_thumbnail
from upload_youtube import upload

GPT = OpenAI()

MAX_SHORTS_SEC = 59.0   # Shorts 判定のための上限（安全マージン）

# combos.yaml 読み込み
with open(BASE / "combos.yaml", encoding="utf-8") as f:
    COMBOS = yaml.safe_load(f)["combos"]

def reset_temp():
    if TEMP.exists():
        rmtree(TEMP)
    TEMP.mkdir(exist_ok=True)

def sanitize_title(raw: str) -> str:
    # 先頭の番号・箇条書き記号を除去
    title = re.sub(r"^\s*(?:\d+\s*[.)]|[-•・])\s*", "", raw)
    # 余分な空白を正規化
    title = re.sub(r"[\s\u3000]+", " ", title).strip()
    return title[:97] + "…" if len(title) > 100 else title or "Auto Video"

TOP_KEYWORDS = ["ホテル英語", "空港英会話", "レストラン英語", "仕事で使う英語", "旅行英会話", "接客英語"]

def score_title(t: str) -> int:
    t = t.strip()
    score = 0
    if any(t.startswith(k) for k in TOP_KEYWORDS): score += 20
    if re.search(r"\d+|チェックイン|注文|予約|例文|空港|ホテル|レストラン|面接|受付", t): score += 15
    score += max(0, 15 - max(0, len(t) - 28))
    if re.search(r"(英語|English)", t): score += 10
    return score

LANG_NAME = {
    "en": "English", "pt": "Portuguese", "id": "Indonesian",
    "ja": "Japanese","ko": "Korean",     "es": "Spanish",
}

# ---------- ✅ シードフレーズ ----------
def _make_seed_phrase(topic: str, lang_code: str) -> str:
    lang = LANG_NAME.get(lang_code, "English")
    prompt = (
        f"Write one very short opening sentence in {lang} "
        f"to introduce a language-learning roleplay scene about: {topic}.\n"
        "It should sound natural and motivating, ≤12 words.\n"
        "Examples: 'Let’s practice a hotel check-in.' / 'Time to learn how to order food.'"
    )
    try:
        rsp = GPT.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
        )
        return rsp.choices[0].message.content.strip()
    except Exception:
        return ""

def make_title(topic, title_lang: str):
    if title_lang == "ja":
        prompt = (
            "You are a YouTube copywriter.\n"
            "Generate 5 concise Japanese titles (each ≤28 JP chars) for a LANGUAGE-LEARNING video.\n"
            "Each title must start with a strong scenario keyword and include a benefit.\n"
            f"Scenario/topic: {topic}\n"
            "Return 5 lines only."
        )
    else:
        prompt = (
            f"You are a YouTube copywriter.\n"
            f"Generate 5 concise {LANG_NAME.get(title_lang,'English')} titles (each ≤55 chars).\n"
            "Each title should be clear and benefit-driven.\n"
            f"Topic: {topic}\n"
            "Return 5 lines only."
        )
    rsp = GPT.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    cands = [sanitize_title(x) for x in rsp.choices[0].message.content.split("\n") if x.strip()]
    if title_lang == "ja":
        cands = [t if any(t.startswith(k) for k in TOP_KEYWORDS) else f"{topic} {t}" for t in cands]
        return sorted(cands, key=score_title, reverse=True)[0][:28]
    else:
        return max(cands, key=len)[:55]

def make_desc(topic, title_lang: str):
    prompt_desc = (
        f"Write one sentence (≤90 chars) in {LANG_NAME.get(title_lang,'English')} "
        f"summarising \"{topic}\" and ending with a call-to-action."
    )
    rsp = GPT.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt_desc}],
        temperature=0.5,
    )
    base = rsp.choices[0].message.content.strip()

    prompt_tags = (
        f"List 2 or 3 popular hashtags in {LANG_NAME.get(title_lang,'English')} "
        "used by language learners. Only hashtags, space separated."
    )
    tag_rsp = GPT.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt_tags}],
        temperature=0.3,
    )
    hashtags = tag_rsp.choices[0].message.content.strip().replace("\n"," ")
    return f"{base} {hashtags}"

def make_tags(topic, audio_lang, subs, title_lang):
    tags = [
        topic, "language learning",
        f"{LANG_NAME.get(title_lang,'English')} study",
        f"{LANG_NAME.get(title_lang,'English')} practice",
    ]
    if title_lang == "ja":
        tags.extend(["英会話","旅行英会話","接客英語","仕事で使う英語"])
    for code in subs[1:]:
        if code in LANG_NAME:
            tags.extend([f"{LANG_NAME[code]} subtitles", f"Learn {LANG_NAME[code]}"])
    return list(dict.fromkeys(tags))[:15]

def _concat_trim_to(mp_paths, max_sec):
    """mp3 を連結して max_sec で打ち切り。"""
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
    (TEMP/"full_raw.mp3").unlink(missing_ok=True)
    combined.export(TEMP/"full_raw.mp3", format="mp3")
    return new_durs

def run_all(topic, turns, privacy, do_upload, chunk_size):
    for combo in COMBOS:
        audio_lang  = combo["audio"]
        subs        = combo["subs"]
        account     = combo.get("account","default")
        title_lang  = combo.get("title_lang", subs[1] if len(subs)>1 else audio_lang)
        logging.info(f"=== Combo: {audio_lang}, subs={subs}, account={account}, title_lang={title_lang} ===")
        run_one(topic, turns, audio_lang, subs, title_lang,
                privacy, account, do_upload, chunk_size)

def run_one(topic, turns, audio_lang, subs, title_lang,
            yt_privacy, account, do_upload, chunk_size):
    reset_temp()

    topic_for_dialogue = translate(topic, audio_lang) if audio_lang != "ja" else topic
    seed_phrase = _make_seed_phrase(topic_for_dialogue, audio_lang)
    dialogue = make_dialogue(topic_for_dialogue, audio_lang, turns, seed_phrase=seed_phrase)

    mp_parts, sub_rows = [], [[] for _ in subs]
    for i,(spk,line) in enumerate(dialogue,1):
        if not line.strip(): continue
        mp = TEMP/f"{i:02d}.mp3"
        speak(audio_lang, spk, line, mp)
        mp_parts.append(mp)
        for r,lang in enumerate(subs):
            sub_rows[r].append(line if lang==audio_lang else translate(line,lang))

    # 60秒以内にトリム
    new_durs = _concat_trim_to(mp_parts, MAX_SHORTS_SEC)
    enhance(TEMP/"full_raw.mp3", TEMP/"full.mp3")

    bg_png = TEMP/"bg.png"
    fetch_bg(topic, bg_png)

    valid_dialogue = [d for d in dialogue if d[1].strip()]
    valid_dialogue = valid_dialogue[:len(new_durs)]

    lines_data = []
    for i,((spk,txt),dur) in enumerate(zip(valid_dialogue,new_durs)):
        row=[spk]
        for r in range(len(subs)):
            row.append(sub_rows[r][i])
        row.append(dur)
        lines_data.append(row)

    (TEMP/"lines.json").write_text(json.dumps(lines_data,ensure_ascii=False,indent=2),encoding="utf-8")

    if args.lines_only: return

    thumb = TEMP/"thumbnail.jpg"
    thumb_lang = subs[1] if len(subs)>1 else audio_lang
    make_thumbnail(topic, thumb_lang, thumb)

    stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
    final_mp4=OUTPUT/f"{audio_lang}-{'_'.join(subs)}_{stamp}.mp4"
    final_mp4.parent.mkdir(parents=True,exist_ok=True)

    cmd=[
        "python", str(BASE/"chunk_builder.py"),
        str(TEMP/"lines.json"), str(TEMP/"full.mp3"), str(bg_png),
        "--chunk", str(chunk_size),
        "--rows", str(len(subs)),
        "--out", str(final_mp4),
    ]
    logging.info("🔹 chunk_builder cmd: %s"," ".join(cmd))
    subprocess.run(cmd,check=True)

    if not do_upload: return

    title=make_title(topic,title_lang)
    desc=make_desc(topic,title_lang)
    tags=make_tags(topic,audio_lang,subs,title_lang)

    upload(video_path=final_mp4,title=title,desc=desc,tags=tags,
           privacy=yt_privacy,account=account,thumbnail=thumb,
           default_lang=audio_lang)

if __name__=="__main__":
    logging.basicConfig(level=logging.INFO,format="%(asctime)s [%(levelname)s] %(message)s")
    ap=argparse.ArgumentParser()
    ap.add_argument("topic",help="会話テーマ")
    ap.add_argument("--turns",type=int,default=8)
    ap.add_argument("--privacy",default="unlisted",choices=["public","unlisted","private"])
    ap.add_argument("--lines-only",action="store_true")
    ap.add_argument("--no-upload",action="store_true")
    ap.add_argument("--chunk",type=int,default=9999,help="Shortsは分割せず1本推奨")
    args=ap.parse_args()
    run_all(args.topic,args.turns,args.privacy,not args.no_upload,args.chunk)
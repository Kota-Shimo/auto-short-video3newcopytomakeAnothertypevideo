#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# split_podcast_min.sh – "ワンクリック Podcast 自動生成" の最小構成
#   画像入力・動画編集を完全に排除し、
#   ① GPT で対話スクリプト生成 → ② ElevenLabs TTS で音声化 → ③ mp3 結合
#   までを 1 コマンドで行うモジュールを生成します。
#   （auto_podcast ディレクトリ直下で実行してください）
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"

# ───────────────────── base config ─────────────────────
cat > config.py <<'PY'
# config.py  – 2 スピーカー用ボイスを全言語で分離
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

# ── ディレクトリ ───────────────────────────────
BASE   = Path(__file__).parent
INPUT  = BASE / "input"
OUTPUT = BASE / "output"
TEMP   = BASE / "temp"
for d in (INPUT, OUTPUT, TEMP): d.mkdir(exist_ok=True)

# ── API キー ──────────────────────────────────
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")

# ── OpenAI TTS 用 (Alice 用, Bob 用) ───────────
VOICE_MAP = {
    "en": ("alloy",   "echo"),     # 英語 : 落ち着いた男性 / 落ち着いた女性
    "ja": ("nova",    "shimmer"),  # 日本語 : 女性 / 中性
    "pt": ("fable",   "onyx"),     # ポルトガル語 : やや明るい / 低め
    "id": ("alloy",   "fable"),    # インドネシア語 : 落ち着き / 明るめ
}
# 必要に応じてボイス名は自由に差し替えてください
PY
# ───────────────────── dialogue generator ───────────────
cat > dialogue.py <<'PY'
# dialogue.py
"""Generate a two-person *discussion / debate* script via GPT-4o in any language."""

from openai import OpenAI
from config import OPENAI_API_KEY
from typing import List, Tuple

openai = OpenAI(api_key=OPENAI_API_KEY)

def make_dialogue(topic: str, lang: str, turns: int = 8) -> List[Tuple[str, str]]:
    """
    topic : 議論テーマ
    lang  : 'en', 'ja', 'pt', 'id' … 出力言語コード
    turns : Alice→Bob の往復回数（1 往復 = 2 行）
    戻り値: [(speaker, text), ...]  ※必ず len == turns*2
    """
    prompt = (
        f"Stage a lively *discussion* between Alice and Bob in {lang}.\n"
        f"Topic: \"{topic}\". Exactly {turns} exchanges (Alice starts).\n\n"
        "• Each utterance should present a clear standpoint, argument, or rebuttal.\n"
        "• Friendly tone but contrasting opinions when appropriate.\n"
        "• 20–35 words per line.\n"
        "• Return ONLY the dialogue, one line each, formatted as:\n"
        "  Alice: ...\n  Bob:   ...\n"
    )
    rsp = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )

    raw_lines = [
        l.strip() for l in rsp.choices[0].message.content.splitlines()
        if l.strip().startswith(("Alice:", "Bob:"))
    ]

    # ---- 必要数にトリミング / パディング --------------------------
    max_lines = turns * 2                     # 期待行数
    raw_lines = raw_lines[:max_lines]         # 余分をカット

    while len(raw_lines) < max_lines:         # 足りなければ補完
        speaker = "Alice" if len(raw_lines) % 2 == 0 else "Bob"
        raw_lines.append(f"{speaker}: ...")

    # ---- 整形して返却 -------------------------------------------
    return [(spk.strip(), txt.strip())
            for spk, txt in (ln.split(":", 1) for ln in raw_lines)]

PY
cat > combos.yaml <<'PY'
combos:
  - audio: en
    subs:  [en, pt]
    account: acc1       # ← 1 本目用トークン

  - audio: en
    subs:  [en, id]
    account: acc2       # ← 2 本目用

  - audio: en
    subs:  [en, ja]
    account: acc3       # ← 3 本目用

  # combos.yaml ─ 追加分だけ抜粋
  - audio: ja          # 日本語音声
    subs:  [ja, en]    # 上段: 日本語　下段: 英語
    account: acc4      # ← acc4 用トークン

  - audio: ja
    subs: [ja, ko]     # 上段: 日本語　下段: 韓国語
    account: acc5

  - audio: ja
    subs: [ja, id]     # 上段: 日本語　下段: インドネシア語
    account: acc6
PY

# ───────────────────── tts module ───────────────────────
cat > tts.py <<'PY'
from pathlib import Path
from elevenlabs import generate as tts_gen
from config import ELEVEN_API_KEY, VOICE_A, VOICE_B

# -------------------------------------------------
# 公開サンプルの音声 ID（無料枠で利用可）
# 使いたい声があればここか .env で上書きしてください
VOICE_MAP = {
    "Rachel": "21m00Tcm4TlvDq8ikWAM",
    "Adam":   "OmEnGXU7trwJsZ3jMPl8",
}
# -------------------------------------------------

def line_to_voice(speaker: str, text: str, out: Path):
    """
    speaker : 'Alice' または 'Bob' など
    text    : セリフ
    out     : mp3 書き出し先 Path
    """
    # 1) .env の VOICE_A / VOICE_B を最優先
    if speaker.lower() == "alice":
        vid = VOICE_A or VOICE_MAP["Rachel"]
    else:
        vid = VOICE_B or VOICE_MAP["Adam"]

    # 2) fallback — 万一 ID が空なら公開 ID を使用
    if not vid:
        vid = VOICE_MAP["Rachel"]

    # 3) ElevenLabs にリクエスト
    if not ELEVEN_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY が設定されていません。")

    out.write_bytes(
        tts_gen(
            api_key=ELEVEN_API_KEY,
            text=text,
            voice=vid,
        )
    )
PY
# ───────────────────── podcast builder ──────────────────
cat > topic_picker.py <<'PY'
name: Auto-Podcast-Daily

on:
  schedule:
    - cron: "15 3 * * *"   # 毎日 UTC 03:15 ≒ JST 12:15
  workflow_dispatch:       # 手動トリガーも可

jobs:
  build-upload:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install deps
        run: |
          python -m pip install -U pip
          pip install -r requirements.txt

      - name: Restore YouTube token
        env:
          YT_TOKEN_B64: ${{ secrets.YOUTUBE_TOKEN_PKL }}
        run: |
          mkdir -p tokens
          echo "$YT_TOKEN_B64" | base64 -d > tokens/token_default.pkl

      - name: Pick topic
        id: topic
        run: |
          TOPIC=$(python topic_picker.py)
          echo "topic=$TOPIC" >> $GITHUB_OUTPUT

      - name: Generate & upload
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          UNSPLASH_ACCESS_KEY: ${{ secrets.UNSPLASH_ACCESS_KEY }}
        run: |
          python main.py "${{ steps.topic.outputs.topic }}" --turns 6 --privacy public

PY

cat > tts_openai.py <<'PY'
# tts_openai.py
"""OpenAI TTS wrapper – language-aware & two-speaker support."""

from pathlib import Path
from openai import OpenAI
from config import OPENAI_API_KEY, VOICE_MAP

client = OpenAI(api_key=OPENAI_API_KEY)

# フォールバック用（言語が VOICE_MAP に無い場合）
FALLBACK_VOICES = ("alloy", "echo")  # (Alice, Bob)

def speak(lang: str, speaker: str, text: str, out_path: Path):
    """
    lang     : 'en', 'ja', 'pt', 'id' など
    speaker  : 'Alice' / 'Bob' で声を切替
    text     : セリフ
    out_path : 書き出し先 .mp3
    """
    v_a, v_b = VOICE_MAP.get(lang, FALLBACK_VOICES)
    voice_id = v_a if speaker.lower() == "alice" else v_b

    resp = client.audio.speech.create(
        model="tts-1",          # 高音質は "tts-1-hd"
        voice=voice_id,
        input=text
    )
    out_path.write_bytes(resp.content)

PY
# ───────────────────── podcast builder ──────────────────
cat > podcast.py <<'PY'
from pathlib import Path
from pydub import AudioSegment

def concat_mp3(parts:list[Path],out:Path):
    merged=AudioSegment.empty()
    for p in parts:
        merged+=AudioSegment.from_file(p)
    merged.export(out,format="mp3")
PY
# ───────────────────── main runner ──────────────────────
cat > bg_image.py <<'PY'
"""
bg_image.py – Unsplash から検索キーワードで **横向き** 画像を取得し，
中央トリムして 1920×1080 PNG を生成（失敗時は単色）。
"""
from pathlib import Path
import logging, io, requests
from PIL import Image, ImageOps
from config import UNSPLASH_ACCESS_KEY

# ------------------------------------------------------------
W, H = 1920, 1080        # 横動画 Full-HD 解像度

def fetch(topic: str, out_png: Path) -> bool:
    """
    Unsplash Random API で横向き (landscape) 画像を取得し，
    1920×1080 にフィットさせて保存する。
    """
    if not UNSPLASH_ACCESS_KEY:
        logging.warning("[Unsplash] KEY 未設定 → 単色背景")
        _fallback_solid(out_png)
        return False

    url = (
        "https://api.unsplash.com/photos/random"
        f"?query={requests.utils.quote(topic)}"
        f"&orientation=landscape&client_id={UNSPLASH_ACCESS_KEY}"
    )
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        img_url   = r.json()["urls"]["regular"]
        img_bytes = requests.get(img_url, timeout=15).content
        _resize_1920x1080(img_bytes, out_png)
        return True
    except Exception as e:
        logging.exception("[Unsplash] %s", e)
        _fallback_solid(out_png)
        return False

# ------------------------------------------------------------
def _resize_1920x1080(img_bytes: bytes, out_png: Path):
    """ImageOps.fit で黒帯なし中央フィット → 1920×1080 で保存"""
    with Image.open(io.BytesIO(img_bytes)) as im:
        fitted = ImageOps.fit(im, (W, H), Image.LANCZOS, centering=(0.5, 0.5))
        fitted.save(out_png, "PNG", optimize=True)

# 単色フォールバック
def _fallback_solid(out_png: Path, color=(10, 10, 10)):
    Image.new("RGB", (W, H), color).save(out_png, "PNG")
PY

cat > subtitle_video.py <<'PY'
# ================= subtitle_video.py =================
from moviepy import (
    ImageClip, TextClip, AudioFileClip, ColorClip, concatenate_videoclips
)
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
import os, unicodedata as ud, re, textwrap
from pathlib import Path

# ---------- フォント設定 ----------
FONT_DIR  = Path(__file__).parent / "fonts"
FONT_LATN = str(FONT_DIR / "RobotoSerif_36pt-Bold.ttf")
FONT_JP   = str(FONT_DIR / "NotoSansJP-Bold.ttf")
FONT_KO   = str(FONT_DIR / "malgunbd.ttf")

# ---------- X 位置ずらし ----------
SHIFT_X = 0                    # 横動画なので中央寄せ
def xpos(w: int) -> int:
    return (SCREEN_W - w) // 2 + SHIFT_X

# ---------- CJK 折り返し ----------
def wrap_cjk(text: str, width: int = 16) -> str:
    if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", text):
        return "\n".join(textwrap.wrap(text, width, break_long_words=True))
    return text

# ---------- フォント存在チェック ----------
for f in (FONT_LATN, FONT_JP, FONT_KO):
    if not os.path.isfile(f):
        raise FileNotFoundError(f"Font not found: {f}")

def pick_font(text: str) -> str:
    for ch in text:
        name = ud.name(ch, "")
        if "HANGUL" in name:
            return FONT_KO
        if any(tag in name for tag in ("CJK", "HIRAGANA", "KATAKANA")):
            return FONT_JP
    return FONT_LATN

# ============ レイアウト定数（横動画用） ============
SCREEN_W, SCREEN_H = 1920, 1080
DEFAULT_FSIZE_TOP  = 75   # ← デフォルト上段サイズ
DEFAULT_FSIZE_BOT  = 70   # ← デフォルト下段サイズ
TEXT_W             = 1500
POS_Y              = 880
LINE_GAP           = 26
BOTTOM_MARGIN      = 30
PAD_X, PAD_Y       = 22, 16
# ===================================================

# ---------- 半透明黒帯 ----------
def _bg(txt: TextClip) -> ColorClip:
    return ColorClip((txt.w + PAD_X * 2, txt.h + PAD_Y * 2), (0, 0, 0)).with_opacity(0.55)

# ---------- メインビルド関数 ----------
def build_video(
    lines,
    bg_path,
    voice_mp3,
    out_mp4,
    rows: int = 2,
    fsize_top: int = DEFAULT_FSIZE_TOP,
    fsize_bot: int = DEFAULT_FSIZE_BOT,
):
    """
    lines : [(speaker, row1_text, row2_text, duration_sec), ...]
    rows  : 1 = 上段のみ / 2 = 上段+下段
    fsize_top / fsize_bot : 字幕フォントサイズを外部から可変指定
    """
    bg_base = ImageClip(bg_path).resized((SCREEN_W, SCREEN_H))
    clips = []

    for speaker, *row_texts, dur in lines:
        # ----- 上段 -----
        top_body = wrap_cjk(row_texts[0])
        top_txt  = f"{speaker}: {top_body}"
        top_clip = TextClip(
            text=top_txt,
            font=pick_font(top_body),
            font_size=fsize_top,
            color="white", stroke_color="black", stroke_width=4,
            method="caption", size=(TEXT_W, None),
        )
        top_bg   = _bg(top_clip)

        elem = [
            top_bg  .with_position((xpos(top_bg.w),  POS_Y - PAD_Y)),
            top_clip.with_position((xpos(top_clip.w), POS_Y)),
        ]
        block_h = top_bg.h

        # ----- 下段 -----
        if rows >= 2:
            bot_body = wrap_cjk(row_texts[1]) + "\n "
            bot_clip = TextClip(
                text=bot_body,
                font=pick_font(bot_body),
                font_size=fsize_bot,
                color="white", stroke_color="black", stroke_width=4,
                method="caption", size=(TEXT_W, None),
            )
            bot_bg = _bg(bot_clip)
            y_bot  = POS_Y + top_bg.h + LINE_GAP
            elem += [
                bot_bg  .with_position((xpos(bot_bg.w),  y_bot - PAD_Y)),
                bot_clip.with_position((xpos(bot_clip.w), y_bot)),
            ]
            block_h += LINE_GAP + bot_bg.h

        # ----- はみ出し補正 -----
        overflow = POS_Y + block_h + BOTTOM_MARGIN - SCREEN_H
        if overflow > 0:
            elem = [c.with_position((c.pos(0)[0], c.pos(0)[1] - overflow)) for c in elem]

        # ----- 合成 -----
        comp = CompositeVideoClip([bg_base, *elem]).with_duration(dur)
        clips.append(comp)

    video = concatenate_videoclips(clips, method="compose").with_audio(AudioFileClip(voice_mp3))
    video.write_videofile(out_mp4, fps=30, codec="libx264", audio_codec="aac")
# =====================================================
# =====================================================
PY
# =====================================================
cat > translate.py <<'PY'
# translate.py
"""GPT-ベースの汎用翻訳ユーティリティ – 任意ターゲット言語対応
   ◎ リトライ／改行除去／失敗プレースホルダ付き改良版
"""
from __future__ import annotations

import re, time, random, logging
from openai import OpenAI
from config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)

# ──────────────────────────────────────────────
# 既に目的言語らしければスキップする簡易判定
# （en / ja / ko のみ厳密、その他は常に翻訳）
# ──────────────────────────────────────────────
def _looks_like(text: str, lang: str) -> bool:
    if lang == "en":
        return all(ord(c) < 128 for c in text)           # 完全 ASCII
    if lang == "ja":
        return (bool(set(text) & {chr(i) for i in range(0x3040, 0x30FF)})  # ひらカナ
                or bool(re.search(r"[\u4E00-\u9FFF]", text)))              # 漢字
    if lang == "ko":
        return bool(re.search(r"[\uAC00-\uD7AF]", text)) # ハングル
    return False
# ──────────────────────────────────────────────


MAX_RETRY = 3      # ↩ API の一時失敗に備えて最大 3 回
BACKOFF   = 1.5    # ↩ リトライ間隔（秒）

def translate(text: str, target: str) -> str:
    """
    text   : 原文
    target : 'en', 'ja', 'ko', 'id', 'pt', … ISO-639-1
    失敗時 : `[ID unavailable]` のような目印を返す
    """
    if _looks_like(text, target):
        return text

    system_prompt = (
        "You are a professional translator. "
        f"Translate the following text into {target.upper()} accurately. "
        "Return the translation only."
    )

    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            rsp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": text},
                ],
                temperature=0.2,
            )
            out = rsp.choices[0].message.content.strip().replace("\n", " ")
            return out or text        # 応答空なら原文で代用
        except Exception as e:
            last_err = e
            if attempt == MAX_RETRY:          # これが最後の試行
                break
            time.sleep(BACKOFF + random.random())  # 少しジッターを入れて待機

    # ---- ここに来たら全リトライ失敗 ----
    logging.warning("Translate error (%s → %s): %s", text[:40], target, last_err)
    return f"[{target.upper()} unavailable]"

PY
cat > upload_youtube.py <<'PY'
# ================= upload_youtube.py =================
"""
YouTube へ動画をアップロードするユーティリティ。
複数アカウント対応（トークンを account ラベルで切替）。
"""

from pathlib import Path
from typing import List, Optional
import pickle, re, logging

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http      import MediaFileUpload
from google.auth.transport.requests import Request

# ── OAuth / API 設定 ─────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
DEFAULT_TOKEN_DIR = Path("tokens")          # トークン保存フォルダ
DEFAULT_TOKEN_DIR.mkdir(exist_ok=True)
# ────────────────────────────────────────────────────


# ------------------------------------------------------
# ✅ 追加: カスタムサムネイルをセットするヘルパー
def _set_thumbnail(service, video_id: str, thumb_path: Path):
    """アップロード済み video_id に thumb_path を適用"""
    service.thumbnails().set(
        videoId=video_id,
        media_body=str(thumb_path)
    ).execute()
# ------------------------------------------------------


def _get_service(account_label: str = "default"):
    """
    account_label : 任意の識別子。複数アカウントで token_<label>.pkl を使い分ける。
    """
    token_path = DEFAULT_TOKEN_DIR / f"token_{account_label}.pkl"

    if token_path.exists():
        creds = pickle.loads(token_path.read_bytes())
        # 有効期限切れなら自動リフレッシュ
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(
            "client_secret.json", SCOPES
        )
        creds = flow.run_local_server(port=0)
        token_path.write_bytes(pickle.dumps(creds))

    return build("youtube", "v3", credentials=creds)


# ── タイトル安全化（念のための最終チェック）────────────────
def _sanitize_title(raw: str) -> str:
    """空・改行入りを防ぎ、100字以内に丸める"""
    title = re.sub(r"[\s\u3000]+", " ", raw).strip()
    if len(title) > 100:
        title = title[:97] + "..."
    return title or "Auto Short #Shorts"
# ────────────────────────────────────────────────────


def upload(
    video_path: Path,
    title: str,
    desc: str,
    tags: Optional[List[str]] = None,
    privacy: str = "public",
    account: str = "default",
    thumbnail: Path | None = None,          # ★ 追加
):
    """
    video_path : Path to .mp4
    title      : YouTube title
    desc       : Description（0–5000 文字）
    tags       : ["tag1", ...]   (optional, 最大 500 個)
    privacy    : "public" / "unlisted" / "private"
    account    : token ラベル（複数アカウント切替用）
    thumbnail  : Path to .jpg / .png（カスタムサムネ）※任意
    """
    service = _get_service(account)

    # ---- 最終ガード ----
    title = _sanitize_title(title)
    if len(desc) > 5000:
        desc = desc[:4997] + "..."

    body = {
        "snippet": {
            "title":       title,
            "description": desc,
            "tags":        tags or [],
            "categoryId":  "27",        # 27 = Education
        },
        "status": {
            "privacyStatus": privacy,
        },
    }

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    req   = service.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )
    resp = req.execute()

    video_id = resp["id"]
    url = f"https://youtu.be/{video_id}"
    print("✅ YouTube Upload Done →", url)

    # ---- カスタムサムネイル ----
    if thumbnail and thumbnail.exists():
        _set_thumbnail(service, video_id, thumbnail)
        print("🖼  Custom thumbnail set.")

    logging.info("YouTube URL: %s (account=%s)", url, account)
    return url
# ====================================================
# ====================================================
PY

cat > thumbnail.py <<'PY'
# thumbnail.py – perfectly centered bright glass panel + pure-white caption
from pathlib import Path
from io import BytesIO
import textwrap, logging, requests
from PIL import (
    Image, ImageDraw, ImageFont, ImageFilter,
    ImageEnhance, ImageOps                    # ImageOps.fit 用
)
from openai import OpenAI
from config import OPENAI_API_KEY, UNSPLASH_ACCESS_KEY
from translate import translate

# ------------ Canvas ---------------------------------
W, H = 1280, 720

# ------------ Font set --------------------------------
FONT_DIR   = Path(__file__).parent / "fonts"         # 既存字幕と同じ場所
FONT_LATN  = FONT_DIR / "RobotoSerif_36pt-Bold.ttf"  # ラテン
FONT_CJK   = FONT_DIR / "NotoSansJP-Bold.ttf"        # 漢字・かな
FONT_KO    = FONT_DIR / "malgunbd.ttf"               # 한글 (Windows 標準 Bold)

for fp in (FONT_LATN, FONT_CJK, FONT_KO):
    if not fp.exists():
        raise FileNotFoundError(f"Font missing: {fp}")

def pick_font(text: str) -> str:
    """文字コードで適切なフォントを返す"""
    for ch in text:
        cp = ord(ch)
        if 0xAC00 <= cp <= 0xD7A3:        # 한글
            return str(FONT_KO)
        if (0x4E00 <= cp <= 0x9FFF) or (0x3040 <= cp <= 0x30FF):
            return str(FONT_CJK)          # CJK/かな
    return str(FONT_LATN)

# ------------ Caption sizes / wrapping ---------------
F_H1, F_H2          = 100, 70
WRAP_H1, WRAP_H2    = 16, 20

# ------------ Badge -----------------------------------
BADGE_BASE   = "Lesson"
BADGE_SIZE   = 60
BADGE_POS    = (40, 30)

client = OpenAI(api_key=OPENAI_API_KEY)

# ------------------------------------------------------ Unsplash BG
def _unsplash(topic: str) -> Image.Image:
    """
    Unsplash landscape → 1280×720 central fit.
    黒帯なしで必ず埋める。失敗時はダークグレー単色。
    """
    if not UNSPLASH_ACCESS_KEY:
        return Image.new("RGB", (W, H), (35, 35, 35))

    url = (
        "https://api.unsplash.com/photos/random"
        f"?query={requests.utils.quote(topic)}"
        f"&orientation=landscape&client_id={UNSPLASH_ACCESS_KEY}"
    )
    try:
        r = requests.get(url, timeout=15); r.raise_for_status()
        img_url = r.json().get("urls", {}).get("regular")
        if not img_url:
            raise ValueError("Unsplash: no image url")
        img = Image.open(BytesIO(requests.get(img_url, timeout=15).content)).convert("RGB")
    except Exception:
        logging.exception("[Unsplash]")
        return Image.new("RGB", (W, H), (35, 35, 35))

    img = ImageOps.fit(img, (W, H), Image.LANCZOS, centering=(0.5, 0.5))
    img = img.filter(ImageFilter.GaussianBlur(2)).convert("RGBA")
    img.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, 77)))   # 30 % 暗幕
    return img

# ------------------------------------------------------ GPT Caption
def _caption(topic: str, lang: str) -> str:
    prompt = (
        "You are a YouTube Shorts copywriter. "
        f"Give TWO catchy phrases (≤18 chars) in {lang.upper()} "
        f"about: {topic}. Separate with '|'."
    )
    return client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    ).choices[0].message.content.strip()

# ------------------------------------------------------ helpers
def _txt_size(draw: ImageDraw.ImageDraw, txt: str, font: ImageFont.FreeTypeFont):
    if hasattr(draw, "textbbox"):
        x1, y1, x2, y2 = draw.textbbox((0, 0), txt, font=font)
        return x2 - x1, y2 - y1
    return draw.textsize(txt, font=font)

# ------------------------------------------------------ draw core
def _draw(img: Image.Image, cap: str, badge_txt: str) -> Image.Image:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    draw = ImageDraw.Draw(img)

    l1, l2  = (cap.split("|") + [""])[:2]
    l1, l2  = l1.strip(), l2.strip()

    f1 = ImageFont.truetype(pick_font(l1),          F_H1)
    f2 = ImageFont.truetype(pick_font(l2 or l1),    F_H2)

    t1 = textwrap.fill(l1, WRAP_H1)
    t2 = textwrap.fill(l2, WRAP_H2) if l2 else ""

    w1, h1 = _txt_size(draw, t1, f1)
    w2, h2 = (_txt_size(draw, t2, f2) if t2 else (0, 0))

    stroke = 4
    tw = max(w1, w2) + stroke*2
    th = h1 + (h2 + 12 if t2 else 0)

    # ---- panel auto-padding ---------------------------------------
    BASE_PAD_X, BASE_PAD_Y = 60, 40
    pad_x = min(BASE_PAD_X, max(20, (W - tw)//2))
    pad_y = min(BASE_PAD_Y, max(20, (H - th)//2))

    pw, ph = tw + pad_x*2, th + pad_y*2
    x_panel = (W - pw)//2
    y_panel = (H - ph)//2
    x_txt   = x_panel + pad_x
    y_txt   = y_panel + pad_y

    # ---- glass panel ---------------------------------------------
    radius = 35
    panel_bg = img.crop((x_panel, y_panel, x_panel+pw, y_panel+ph)) \
                  .filter(ImageFilter.GaussianBlur(12)).convert("RGBA")
    veil     = Image.new("RGBA", (pw, ph), (255,255,255,77))
    panel    = Image.alpha_composite(panel_bg, veil)

    mask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0,0,pw-1,ph-1], radius, fill=255)
    panel.putalpha(mask)

    border = Image.new("RGBA", (pw, ph))
    ImageDraw.Draw(border).rounded_rectangle(
        [0,0,pw-1,ph-1], radius, outline=(255,255,255,120), width=2)
    panel = Image.alpha_composite(panel, border)
    img.paste(panel, (x_panel, y_panel), panel)

    # ---- glow -----------------------------------------------------
    glow = Image.new("RGBA", img.size, (0,0,0,0))
    gd   = ImageDraw.Draw(glow)
    gd.text((x_txt, y_txt), t1, font=f1, fill=(255,255,255,255))
    if t2:
        gd.text((x_txt, y_txt+h1+12), t2, font=f2, fill=(255,255,255,255))
    glow = glow.filter(ImageFilter.GaussianBlur(14))
    glow = ImageEnhance.Brightness(glow).enhance(1.2)
    img.alpha_composite(glow)

    # ---- final text ----------------------------------------------
    draw.text((x_txt, y_txt), t1, font=f1, fill=(255,255,255),
              stroke_width=stroke, stroke_fill=(0,0,0))
    if t2:
        draw.text((x_txt, y_txt+h1+12), t2, font=f2,
                  fill=(255,255,255), stroke_width=stroke, stroke_fill=(0,0,0))

    # ---- badge ----------------------------------------------------
    bf  = ImageFont.truetype(pick_font(badge_txt), BADGE_SIZE)
    draw.text(BADGE_POS, badge_txt, font=bf,
              fill=(255,255,255), stroke_width=3, stroke_fill=(0,0,0))
    return img

# ------------------------------------------------------ public
def make_thumbnail(topic: str, lang: str, out: Path):
    bg    = _unsplash(topic)
    cap   = _caption(topic, lang)
    badge = translate(BADGE_BASE, lang) or BADGE_BASE
    thumb = _draw(bg, cap, badge)
    thumb.convert("RGB").save(out, "JPEG", quality=92)
    logging.info("🖼️  Thumbnail saved → %s", out.name)

PY

cat > audio_fx.py <<'PY'
# audio_fx.py – “良いマイク風” (deesser 非依存バージョン)
import subprocess, shutil
from pathlib import Path

# -----------------------------------------------------------
# FILTER chain
#   1) highpass 60 Hz         : 空調/机振動カット
#   2) lowpass  15 kHz        : モスキートノイズ抑制
#   3) presence EQ 4 kHz +3dB : 明瞭度
#   4) soft de-ess  8 kHz −2dB: 歯擦音をやや抑える (simple EQ)
#   5) soft compressor        : ratio 2:1 で自然に
#   6) loudnorm (-16 LUFS)    : ポッドキャスト標準ラウドネス
FILTER = (
    "highpass=f=60,"
    "lowpass=f=15000,"
    "equalizer=f=4000:width_type=h:width=150:g=3,"
    "equalizer=f=8000:width_type=h:width=300:g=-2,"
    "acompressor=threshold=-18dB:ratio=2:knee=2:attack=15:release=200,"
    "loudnorm=I=-16:TP=-1.5:LRA=11"
)
# -----------------------------------------------------------

def enhance(in_mp3: Path, out_mp3: Path):
    """
    in_mp3  : 入力 mp3
    out_mp3 : 整音後 mp3
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg が見つかりません。PATH を確認してください。")

    cmd = [
        "ffmpeg", "-y", "-i", str(in_mp3),
        "-af", FILTER,
        "-ar", "48000",                # 48 kHz に統一（必要に応じて 44100）
        str(out_mp3)
    ]

    # 標準出力・エラーをそのまま表示し、失敗時は内容をわかりやすく出力
    proc = subprocess.run(cmd, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg returned {proc.returncode}. "
            "コマンドラインに直接貼り付けてエラー内容を確認してください。\n"
            "deesser フィルタが必要なら、FFmpeg full build を導入する方法もあります。"
        )
PY

cat > audio_fx.py <<'PY'
# audio_fx.py – “良いマイク風” (deesser 非依存バージョン)
import subprocess, shutil
from pathlib import Path

# -----------------------------------------------------------
# FILTER chain
#   1) highpass 60 Hz         : 空調/机振動カット
#   2) lowpass  15 kHz        : モスキートノイズ抑制
#   3) presence EQ 4 kHz +3dB : 明瞭度
#   4) soft de-ess  8 kHz −2dB: 歯擦音をやや抑える (simple EQ)
#   5) soft compressor        : ratio 2:1 で自然に
#   6) loudnorm (-16 LUFS)    : ポッドキャスト標準ラウドネス
FILTER = (
    "highpass=f=60,"
    "lowpass=f=10500,"
    "equalizer=f=4000:width_type=h:width=150:g=3,"
    "equalizer=f=8000:width_type=h:width=300:g=-2,"
    "acompressor=threshold=-18dB:ratio=2:knee=2:attack=15:release=200,"
    "loudnorm=I=-16:TP=-1.5:LRA=11"
)
# -----------------------------------------------------------

def enhance(in_mp3: Path, out_mp3: Path):
    """
    in_mp3  : 入力 mp3
    out_mp3 : 整音後 mp3
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg が見つかりません。PATH を確認してください。")

    cmd = [
        "ffmpeg", "-y", "-i", str(in_mp3),
        "-af", FILTER,
        "-ar", "48000",                # 48 kHz に統一（必要に応じて 44100）
        str(out_mp3)
    ]

    # 標準出力・エラーをそのまま表示し、失敗時は内容をわかりやすく出力
    proc = subprocess.run(cmd, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg returned {proc.returncode}. "
            "コマンドラインに直接貼り付けてエラー内容を確認してください。\n"
            "deesser フィルタが必要なら、FFmpeg full build を導入する方法もあります。"
        )
PY


cat > main.py <<'PY'
# ======================= main.py ==========================
#!/usr/bin/env python
"""
main.py – GPT で会話 → OpenAI TTS → 多段字幕付き縦動画 (1080×1920)
          combos.yaml の組み合わせごとに生成し、
          ── デフォルト: YouTube へ自動アップロード
          ── --no-upload を付けるとローカル出力のみ
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
from audio_fx        import enhance   # 音質フィルタ

GPT = OpenAI()

# ── 言語コンボ読み込み ─────────────────────────────
with open(BASE / "combos.yaml", encoding="utf-8") as f:
    COMBOS = yaml.safe_load(f)["combos"]

# ── TEMP を毎回空に ───────────────────────────────
def reset_temp():
    if TEMP.exists():
        rmtree(TEMP)
    TEMP.mkdir(exist_ok=True)

# ── タイトル整形 ───────────────────────────────────
def sanitize_title(raw: str) -> str:
    title = re.sub(r"[\s\u3000]+", " ", raw).strip()
    return title[:97] + "…" if len(title) > 100 else title or "Auto Short"

# ── 共通: プライマリ言語決定 ────────────────────────
def _primary_lang(audio_lang: str, subs: list[str]) -> str:
    """字幕が 2 行以上あれば 2 行目を優先、無ければ音声言語"""
    return subs[1] if len(subs) > 1 else audio_lang

# ── GPT タイトル ──────────────────────────────────
def make_title(topic: str, audio_lang: str, subs: list[str]) -> str:
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
def make_desc(topic: str, audio_lang: str, subs: list[str]) -> str:
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
    if primary != "en":
        hashtags.append(f"#Learn{primary.upper()}")
    return f"{base} {' '.join(hashtags[:3])}"

# ── メタ tags 生成 ─────────────────────────────────
LANG_NAME = {
    "en": "English", "pt": "Portuguese", "id": "Indonesian",
    "ja": "Japanese", "ko": "Korean", "es": "Spanish"
}
def make_tags(topic: str, audio_lang: str, subs: list[str]) -> list[str]:
    tags = [topic, "language learning", "Shorts",
            f"{LANG_NAME.get(audio_lang,'')} speaking"]
    for code in subs[1:]:
        if code in LANG_NAME:
            tags.extend([f"{LANG_NAME[code]} subtitles", f"Learn {LANG_NAME[code]}"])
    return list(dict.fromkeys(tags))[:15]

# ── 全コンボ処理 ───────────────────────────────────
def run_all(topic: str, turns: int, privacy: str, do_upload: bool):
    for combo in COMBOS:
        run_one(topic, turns,
                combo["audio"], combo["subs"],
                yt_privacy=privacy,
                account   =combo.get("account", "default"),
                do_upload =do_upload)

# ── 単一コンボ処理 ─────────────────────────────────
def run_one(topic: str, turns: int, audio_lang: str, subs: list[str],
            yt_privacy: str, account: str, do_upload: bool):

    reset_temp()

    # 1) 会話スクリプト
    dialogue = make_dialogue(topic, audio_lang, turns)

    # 2) 音声合成 & 翻訳
    mp_parts, durations, sub_rows = [], [], [[] for _ in subs]
    for i, (spk, line) in enumerate(dialogue, 1):
        mp = TEMP / f"{i:02d}.mp3"
        speak(audio_lang, spk, line, mp)
        mp_parts.append(mp)
        durations.append(AudioSegment.from_file(mp).duration_seconds)
        for r, lang in enumerate(subs):
            sub_rows[r].append(line if lang == audio_lang else translate(line, lang))

    concat_mp3(mp_parts, TEMP / "full_raw.mp3")      # まず生音声を結合
    enhance(TEMP / "full_raw.mp3", TEMP / "full.mp3")# 高音質化を適用

    # 3) 背景画像
    bg_png = TEMP / "bg.png"; fetch_bg(topic, bg_png)

    # 4) 動画生成
    stamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    outfile = OUTPUT / f"{audio_lang}-{'_'.join(subs)}_{stamp}.mp4"
    lines   = [(spk, *[row[i] for row in sub_rows], dur)
               for i, ((spk, _), dur) in enumerate(zip(dialogue, durations))]
    build_video(lines, bg_png, TEMP / "full.mp3", outfile, rows=len(subs))
    logging.info("✅ Video saved: %s", outfile.name)

    if not do_upload:
        logging.info("⏭️  --no-upload 指定のためアップロードをスキップ")
        return

    # 5) メタ & アップロード
    title = make_title(topic, audio_lang, subs)
    desc  = make_desc(topic, audio_lang, subs)
    tags  = make_tags(topic, audio_lang, subs)
    upload(outfile, title=title, desc=desc, tags=tags,
           privacy=yt_privacy, account=account)

# ── CLI ───────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("topic", help="会話テーマ (例: 'Japanese cuisine')")
    ap.add_argument("--turns", type=int, default=8)
    ap.add_argument("--privacy", default="unlisted",
                    choices=["public", "unlisted", "private"])
    ap.add_argument("--no-upload", action="store_true",
                    help="動画を生成するだけで YouTube へはアップロードしない")
    args = ap.parse_args()

    run_all(args.topic, turns=args.turns,
            privacy=args.privacy, do_upload=(not args.no_upload))
# =========================================================
PY
# ─────────────────────────────────────────────────────────

echo "✅ Podcast‑only minimal modules generated."

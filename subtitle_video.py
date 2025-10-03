# ================= subtitle_video.py (Shorts最適・確実収まり版) =================
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

# ---------- 画面・レイアウト定数 ----------
SCREEN_W, SCREEN_H = 1080, 1920
SAFE_LR            = 64
SAFE_TOP           = 140
SAFE_BOTTOM        = int(SCREEN_H * 0.20)
TEXT_W             = SCREEN_W - SAFE_LR * 2

DEFAULT_FSIZE_TOP  = 86
DEFAULT_FSIZE_BOT  = 74
LINE_GAP           = 32
BOTTOM_MARGIN      = 28
PAD_X, PAD_Y       = 24, 18
MAX_BLOCK_H        = int(SCREEN_H * 0.30)   # 30% まで拡張して許容

# ---------- X位置 ----------
SHIFT_X = 0
def xpos(w: int) -> int:
    return (SCREEN_W - w) // 2 + SHIFT_X

# ---------- 折り返し ----------
def wrap_cjk(text: str, width: int = 16) -> str:
    if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", text):
        return "\n".join(textwrap.wrap(text, width, break_long_words=True))
    return text

# ---------- 半透明黒帯 ----------
def _bg(txt: TextClip) -> ColorClip:
    return ColorClip((txt.w + PAD_X * 2, txt.h + PAD_Y * 2), (0, 0, 0)).with_opacity(0.45)

# ---------- TextClip 生成 ----------
def _make_text(text: str, fsize: int, stroke: int) -> TextClip:
    return TextClip(
        text=text,
        font=pick_font(text),
        font_size=fsize,
        color="white",
        stroke_color="black",
        stroke_width=stroke,
        method="caption",
        size=(TEXT_W, None),
    )

# ---------- 自動フィット ----------
def _auto_fit(top_body: str, bot_body: str | None, fsize_top: int, fsize_bot: int):
    stroke_top_base = 6
    stroke_bot_base = 4

    size_top = fsize_top
    size_bot = fsize_bot if bot_body else 0

    while True:
        top_clip = _make_text(top_body, size_top, max(2, int(stroke_top_base * size_top / 86)))
        top_bg   = _bg(top_clip)
        block_h  = top_bg.h

        bot_clip = bot_bg = None
        if bot_body:
            bot_clip = _make_text(bot_body, size_bot, max(2, int(stroke_bot_base * size_bot / 74)))
            bot_bg   = _bg(bot_clip)
            block_h += LINE_GAP + bot_bg.h

        fits_height = block_h <= MAX_BLOCK_H
        fits_width  = (top_clip.w <= TEXT_W) and (not bot_clip or bot_clip.w <= TEXT_W)

        if fits_height and fits_width:
            return (size_top, size_bot, top_clip, top_bg, bot_clip, bot_bg, block_h)

        if size_top <= 32:  # 最小32まで粘る
            return (size_top, size_bot, top_clip, top_bg, bot_clip, bot_bg, block_h)

        size_top = max(32, int(size_top * 0.92))
        if bot_body:
            size_bot = max(28, int(size_bot * 0.92))

# ---------- メイン ----------
def build_video(
    lines,
    bg_path,
    voice_mp3,
    out_mp4,
    rows: int = 2,
    fsize_top: int = DEFAULT_FSIZE_TOP,
    fsize_bot: int = DEFAULT_FSIZE_BOT,
):
    bg_base = ImageClip(bg_path).resized((SCREEN_W, SCREEN_H))
    clips = []

    for speaker, *row_texts, dur in lines:
        # --- 上段 ---
        top_body = wrap_cjk(row_texts[0])
        top_disp = f"{speaker}: {top_body}" if speaker else top_body

        bot_body = None
        if rows >= 2 and len(row_texts) > 1 and row_texts[1].strip():
            bot_body = wrap_cjk(row_texts[1]) + "\n "

        # --- 自動フィット ---
        size_top, size_bot, top_clip, top_bg, bot_clip, bot_bg, block_h = \
            _auto_fit(top_disp, bot_body, fsize_top, fsize_bot)

        # --- Y配置（中央寄せ + 安全域内）---
        y_pos = min(int(SCREEN_H * 0.60) - block_h // 2,
                    SCREEN_H - SAFE_BOTTOM - block_h - BOTTOM_MARGIN)
        y_pos = max(SAFE_TOP, y_pos)

        elem = [
            top_bg  .with_position((xpos(top_bg.w),  y_pos - PAD_Y)),
            top_clip.with_position((xpos(top_clip.w), y_pos)),
        ]

        if bot_body and bot_clip and bot_bg:
            y_bot  = y_pos + top_bg.h + LINE_GAP
            elem += [
                bot_bg  .with_position((xpos(bot_bg.w),  y_bot - PAD_Y)),
                bot_clip.with_position((xpos(bot_clip.w), y_bot)),
            ]

        # --- はみ出し最終補正（強制シフトアップ）---
        block_h = top_bg.h + (LINE_GAP + bot_bg.h if bot_body else 0)
        overflow = y_pos + block_h + BOTTOM_MARGIN - SCREEN_H
        if overflow > 0:
            elem = [c.with_position((c.pos(0)[0], c.pos(0)[1] - overflow)) for c in elem]

        comp = CompositeVideoClip([bg_base, *elem]).with_duration(dur)
        clips.append(comp)

    video = concatenate_videoclips(clips, method="compose").with_audio(AudioFileClip(voice_mp3))
    video.write_videofile(
        str(out_mp4),
        fps=30,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=str(Path("temp") / "temp-audio.m4a"),
        remove_temp=True
    )
# =================================================================
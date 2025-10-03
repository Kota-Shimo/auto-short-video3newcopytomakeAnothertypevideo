# ================= subtitle_video.py (Shorts最適・日本語安全・話者チップ・自動縮小) =================
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

def is_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", text))

# ---------- 画面・安全域（Shorts: 縦1080x1920想定） ----------
SCREEN_W, SCREEN_H = 1080, 1920
SAFE_LR            = 64                     # 左右セーフマージン
SAFE_TOP           = 140                    # 上の安全域
SAFE_BOTTOM        = int(SCREEN_H * 0.20)   # 下の安全域（ShortsのUI回避）

TEXT_W             = SCREEN_W - SAFE_LR * 2

# ---------- 既定フォントサイズ（ここから自動縮小あり） ----------
DEFAULT_FSIZE_TOP  = 86   # 上段（音声言語）
DEFAULT_FSIZE_BOT  = 74   # 下段（翻訳字幕）
MIN_FSIZE_TOP      = 38   # 最小上段
MIN_FSIZE_BOT      = 34   # 最小下段

# ---------- レイアウト ----------
LINE_GAP           = 30                  # 上段-下段の隙間
BOTTOM_MARGIN      = 26                  # 追加の下余白（安全域内）
PAD_X, PAD_Y       = 22, 16              # 黒帯の内側パディング
MAX_BLOCK_H        = int(SCREEN_H * 0.30) # 字幕ブロックの最大高さ（超えたら縮小）
CENTER_Y_RATIO     = 0.60                # 画面中央よりやや下に配置
SHIFT_X            = 0                   # 横方向の微調整

def xpos(w: int) -> int:
    return (SCREEN_W - w) // 2 + SHIFT_X

# ---------- CJK 折り返し ----------
def wrap_cjk(text: str, width_cjk: int = 14, width_latn: int = 16) -> str:
    """
    日本語/漢字は1文字が大きいので折り返し幅を短めに。
    MoviePyのcaptionラップも使うが、事前の明示改行で安定させる。
    """
    if is_cjk(text):
        return "\n".join(textwrap.wrap(text, width_cjk, break_long_words=True))
    return "\n".join(textwrap.wrap(text, width_latn, break_long_words=True))

# ---------- 半透明黒帯 ----------
def _bg(txt: TextClip, opacity: float = 0.45) -> ColorClip:
    return ColorClip((txt.w + PAD_X * 2, txt.h + PAD_Y * 2), (0, 0, 0)).with_opacity(opacity)

# ---------- テキストクリップ作成（サイズ指定） ----------
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

# ---------- 話者チップ（小さめのラベル） ----------
def _make_speaker_chip(speaker: str, ref_fsize_top: int):
    """
    話者名を本文から分離。横幅を圧迫しないよう小さいチップに。
    ref_fsize_top: 上段本文のフォントサイズを基準にチップサイズを決める。
    """
    if not speaker:
        return None, None
    chip_fsize = max(22, int(ref_fsize_top * 0.58))
    chip_txt = TextClip(
        text=str(speaker),
        font=pick_font(speaker),
        font_size=chip_fsize,
        color="white",
        stroke_color="black",
        stroke_width=max(1, int(chip_fsize * 0.08)),
        method="caption",
        size=(None, None),
    )
    pad_x, pad_y = 14, 8
    chip_bg = ColorClip((chip_txt.w + pad_x * 2, chip_txt.h + pad_y * 2), (0, 0, 0)).with_opacity(0.45)
    return chip_txt, chip_bg

# ---------- 自動フィット（話者チップ＋上下本文を安全域に収める） ----------
def _auto_fit(top_body: str, bot_body: str | None, speaker: str | None,
              fsize_top: int, fsize_bot: int):
    """
    返り値:
      size_top, size_bot, chip_txt, chip_bg, top_clip, top_bg, bot_clip, bot_bg, block_h, y_pos
    """
    # ストロークはフォントサイズ比でスケール
    def st_top(sz): return max(2, int(6 * sz / DEFAULT_FSIZE_TOP))
    def st_bot(sz): return max(2, int(4 * sz / DEFAULT_FSIZE_BOT))

    size_top = fsize_top
    size_bot = fsize_bot if bot_body else 0

    # 最大 18回（約 0.94^18 ≒ 0.34）で収まらなければ最小フォントで確定
    for _ in range(18):
        # 話者チップ
        chip_txt, chip_bg = _make_speaker_chip(speaker, size_top)

        # 上段
        top_clip = _make_text(top_body, size_top, st_top(size_top))
        top_bg   = _bg(top_clip)

        # 下段
        bot_clip = bot_bg = None
        if bot_body:
            bot_clip = _make_text(bot_body, size_bot, st_bot(size_bot))
            bot_bg   = _bg(bot_clip)

        # 総ブロック高（チップ + 上段 + 下段 + 隙間）
        chip_h   = (chip_bg.h if chip_bg else 0)
        block_h  = (chip_h + (10 if chip_bg else 0)) + top_bg.h
        if bot_bg:
            block_h += LINE_GAP + bot_bg.h

        # 配置Y（中央より下。ただしSAFE_BOTTOMの上に必ず収める）
        center_y = int(SCREEN_H * CENTER_Y_RATIO)
        y_pos    = min(center_y - block_h // 2,
                       SCREEN_H - SAFE_BOTTOM - block_h - BOTTOM_MARGIN)
        # 話者チップが上に出るので、その分の余白も考慮して最低位置を引き上げる
        y_min    = SAFE_TOP + (chip_h + (10 if chip_bg else 0))
        y_pos    = max(y_min, y_pos)

        fits_height = (block_h <= MAX_BLOCK_H) and (y_pos + block_h) <= (SCREEN_H - SAFE_BOTTOM)
        fits_width  = (top_clip.w <= TEXT_W) and (not bot_clip or bot_clip.w <= TEXT_W)

        if fits_height and fits_width:
            return (size_top, size_bot, chip_txt, chip_bg, top_clip, top_bg, bot_clip, bot_bg, block_h, y_pos)

        # 縮小（下段がある場合は一緒に少しずつ）
        next_top = max(MIN_FSIZE_TOP, int(size_top * 0.94))
        if bot_body:
            next_bot = max(MIN_FSIZE_BOT, int(size_bot * 0.94))
        else:
            next_bot = 0

        # 既に最小 → これ以上下げない（はみ出しを避けるため上方に寄せるのは y_pos で対応済み）
        size_top, size_bot = next_top, next_bot
        if size_top == MIN_FSIZE_TOP and (not bot_body or size_bot == MIN_FSIZE_BOT):
            # 最小で確定（多少文字多めでもセーフエリアからはみ出さない）
            return (size_top, size_bot, chip_txt, chip_bg, top_clip, top_bg, bot_clip, bot_bg, block_h, y_pos)

    # 念のためのフォールバック（理論上ここに来ない想定）
    chip_txt, chip_bg = _make_speaker_chip(speaker, size_top)
    top_clip = _make_text(top_body, size_top, st_top(size_top))
    top_bg   = _bg(top_clip)
    bot_clip = bot_bg = None
    if bot_body:
        bot_clip = _make_text(bot_body, size_bot, st_bot(size_bot))
        bot_bg   = _bg(bot_clip)
    block_h  = (chip_bg.h if chip_bg else 0) + (10 if chip_bg else 0) + top_bg.h + ((LINE_GAP + (bot_bg.h if bot_bg else 0)) if bot_bg else 0)
    y_pos    = max(SAFE_TOP, int(SCREEN_H * CENTER_Y_RATIO) - block_h // 2)
    return (size_top, size_bot, chip_txt, chip_bg, top_clip, top_bg, bot_clip, bot_bg, block_h, y_pos)

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
    fsize_top / fsize_bot : 字幕フォントサイズ（基準値）。大きすぎる場合は自動縮小。
    """
    bg_base = ImageClip(bg_path).resized((SCREEN_W, SCREEN_H))
    clips = []

    for speaker, *row_texts, dur in lines:
        # ---------- テキスト本文（事前折り返し） ----------
        top_body_raw = row_texts[0]
        top_body = wrap_cjk(top_body_raw, width_cjk=14, width_latn=18)

        bot_body = None
        if rows >= 2 and len(row_texts) > 1 and row_texts[1].strip():
            bot_body = wrap_cjk(row_texts[1], width_cjk=16, width_latn=22) + "\n "

        # ---------- 自動フィット ----------
        (size_top, size_bot,
         chip_txt, chip_bg,
         top_clip, top_bg,
         bot_clip, bot_bg,
         block_h, y_pos) = _auto_fit(top_body, bot_body, speaker, fsize_top, fsize_bot)

        # ---------- 要素配置 ----------
        elem = [bg_base]

        # 話者チップ（左寄せ、本文の左端に揃える）
        if chip_txt and chip_bg:
            x_left = xpos(top_bg.w)  # 上段背景の左端に合わせる
            y_chip = y_pos - (chip_bg.h + 10)
            elem += [
                chip_bg .with_position((x_left, y_chip)),
                chip_txt.with_position((x_left + (chip_bg.w - chip_txt.w)//2,
                                        y_chip + (chip_bg.h - chip_txt.h)//2)),
            ]

        # 上段
        elem += [
            top_bg  .with_position((xpos(top_bg.w),  y_pos - PAD_Y)),
            top_clip.with_position((xpos(top_clip.w), y_pos)),
        ]

        # 下段
        if bot_body and bot_clip and bot_bg:
            y_bot  = y_pos + top_bg.h + LINE_GAP
            elem += [
                bot_bg  .with_position((xpos(bot_bg.w),  y_bot - PAD_Y)),
                bot_clip.with_position((xpos(bot_clip.w), y_bot)),
            ]

        # ---------- 合成 ----------
        comp = CompositeVideoClip(elem).with_duration(dur)
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
# thumbnail.py – scene (top) + learnable phrase (bottom), GPT-only generation (no fixed dict)
from pathlib import Path
from io import BytesIO
import textwrap, logging, requests, re
from PIL import (
    Image, ImageDraw, ImageFont, ImageFilter,
    ImageEnhance, ImageOps
)
from openai import OpenAI
from config import OPENAI_API_KEY, UNSPLASH_ACCESS_KEY
from translate import translate

# ------------ Canvas ---------------------------------
W, H = 1280, 720

# ------------ Font set --------------------------------
FONT_DIR   = Path(__file__).parent / "fonts"
FONT_LATN  = FONT_DIR / "RobotoSerif_36pt-Bold.ttf"   # Latin
FONT_CJK   = FONT_DIR / "NotoSansJP-Bold.ttf"         # CJK
FONT_KO    = FONT_DIR / "malgunbd.ttf"                # Hangul (Windows Bold)

for fp in (FONT_LATN, FONT_CJK, FONT_KO):
    if not fp.exists():
        raise FileNotFoundError(f"Font missing: {fp}")

def pick_font(text: str) -> str:
    """文字コードで適切なフォントを返す"""
    for ch in text:
        cp = ord(ch)
        if 0xAC00 <= cp <= 0xD7A3:        # Hangul
            return str(FONT_KO)
        if (0x4E00 <= cp <= 0x9FFF) or (0x3040 <= cp <= 0x30FF):
            return str(FONT_CJK)          # CJK/かな
    return str(FONT_LATN)

# ------------ Sizes / wrapping ---------------
# 非Shorts想定だが視認性優先で大きめ
F_H1, F_H2       = 104, 76         # base font sizes (auto downscaleあり)
WRAP_H1, WRAP_H2 = 14, 20          # wrap width (全角系に最適気味)
MAX_PANEL_RATIO  = 0.86            # 文字ブロックの横幅が画面に占められる最大割合

# ------------ Badge -----------------------------------
BADGE_BASE   = "Lesson"
BADGE_SIZE   = 58
BADGE_POS    = (40, 30)

client = OpenAI(api_key=OPENAI_API_KEY)

# ------------------------------------------------------ helpers
def _txt_size(draw: ImageDraw.ImageDraw, txt: str, font: ImageFont.FreeTypeFont):
    if hasattr(draw, "textbbox"):
        x1, y1, x2, y2 = draw.textbbox((0, 0), txt, font=font)
        return x2 - x1, y2 - y1
    return draw.textsize(txt, font=font)

def _clean_piece(s: str) -> str:
    s = s.strip()
    # 余分な引用符・箇条書き・句読点を削る（句点そのものは残す）
    s = re.sub(r'^[\-\•\·\*\"“”\'\s]+', '', s)
    s = re.sub(r'[\\"“”\']+$', '', s)
    s = re.sub(r'\s+', ' ', s)
    return s

def _split_caption(raw: str) -> tuple[str, str]:
    """
    "line1 | line2" の想定。崩れたらできる範囲で復旧。
    """
    if "|" in raw:
        l1, l2 = raw.split("|", 1)
    else:
        # セパレータがない場合、行分割で代替
        parts = [p for p in re.split(r'[\n／/|-]+', raw) if p.strip()]
        if len(parts) >= 2:
            l1, l2 = parts[0], parts[1]
        elif len(parts) == 1:
            l1, l2 = parts[0], ""
        else:
            l1, l2 = "", ""
    return _clean_piece(l1), _clean_piece(l2)

def _downscale_to_fit(draw, t1, t2, f1_path, f2_path, stroke, wrap1, wrap2):
    """
    文字が収まるまでフォントサイズを徐々に縮小。
    """
    size1, size2 = F_H1, F_H2
    while size1 >= 56:  # 下限
        f1 = ImageFont.truetype(f1_path, size1)
        f2 = ImageFont.truetype(f2_path, size2)
        tt1 = textwrap.fill(t1, wrap1) if t1 else ""
        tt2 = textwrap.fill(t2, wrap2) if t2 else ""
        w1, h1 = _txt_size(draw, tt1, f1) if tt1 else (0, 0)
        w2, h2 = _txt_size(draw, tt2, f2) if tt2 else (0, 0)
        tw = max(w1, w2) + stroke * 2
        if tw <= int(W * MAX_PANEL_RATIO):
            return f1, f2, tt1, tt2, (w1, h1), (w2, h2)
        size1 -= 4
        size2 = max(48, size2 - 3)
    # 最後の手段（超小さく）
    f1 = ImageFont.truetype(f1_path, 56)
    f2 = ImageFont.truetype(f2_path, 48)
    tt1 = textwrap.fill(t1, wrap1) if t1 else ""
    tt2 = textwrap.fill(t2, wrap2) if t2 else ""
    w1, h1 = _txt_size(draw, tt1, f1) if tt1 else (0, 0)
    w2, h2 = _txt_size(draw, tt2, f2) if tt2 else (0, 0)
    return f1, f2, tt1, tt2, (w1, h1), (w2, h2)

# ------------------------------------------------------ Unsplash BG
def _unsplash(topic: str) -> Image.Image:
    """
    Unsplash landscape → 1280×720 central fit.
    英語クエリの方が当たりが良いので、英訳トピックを優先。
    """
    if not UNSPLASH_ACCESS_KEY:
        return Image.new("RGB", (W, H), (35, 35, 35))

    try:
        topic_en = translate(topic, "en") or topic
    except Exception:
        topic_en = topic

    url = (
        "https://api.unsplash.com/photos/random"
        f"?query={requests.utils.quote(topic_en)}"
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
    img.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, 77)))   # 暗幕
    return img

# ------------------------------------------------------ GPT Caption
def _caption(topic: str, lang: str) -> str:
    """
    出力は必ず「line1 | line2」形式。固定辞書は使わずGPTのみで生成。
    - line1: 現実のシーン名（例：ホテル / 空港 / レストラン…）1–3語
    - line2: 学べること（3–6語、具体／動詞やセットフレーズ推奨）
    """
    prompt = (
        "You are a YouTube thumbnail copywriter.\n"
        f"Create TWO ultra-concise {lang.upper()} strings for a language-learning video about: {topic}\n"
        "- Line 1: the real-world SCENE in 1–3 words (e.g., ホテル / 空港 / レストラン / 面接)\n"
        "- Line 2: what the viewer will LEARN in 3–6 words, concrete and useful (prefer verbs or set phrases)\n"
        "Return EXACTLY in this format: line1 | line2\n"
        "No emojis. No quotes. Use only the specified language."
    )
    try:
        rsp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5
        )
        return rsp.choices[0].message.content.strip()
    except Exception:
        # 失敗時は topic そのものを返す（分割は後段で処理）
        return topic

# ------------------------------------------------------ draw core
def _draw(img: Image.Image, cap: str, badge_txt: str) -> Image.Image:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    draw = ImageDraw.Draw(img)

    # 必ず2パーツにする
    l1, l2 = _split_caption(cap)

    # フォールバック（line2がないなど）
    if not l1:
        l1 = "Basics"
    if not l2:
        try:
            l2 = translate("Useful phrases", badge_txt) or "Useful phrases"
        except Exception:
            l2 = "Useful phrases"

    # フォント（言語に合わせて自動選択）＋オートダウンスケール
    f1_path = pick_font(l1)
    f2_path = pick_font(l2 or l1)
    stroke  = 4
    f1, f2, t1, t2, (w1, h1), (w2, h2) = _downscale_to_fit(
        draw, l1, l2, f1_path, f2_path, stroke, WRAP_H1, WRAP_H2
    )

    # 枠サイズと配置
    tw = max(w1, w2) + stroke * 2
    th = h1 + (h2 + 14 if t2 else 0)

    BASE_PAD_X, BASE_PAD_Y = 60, 40
    pad_x = min(BASE_PAD_X, max(20, int((W - tw) * 0.5)))
    pad_y = min(BASE_PAD_Y, max(20, int((H - th) * 0.5)))

    pw, ph = tw + pad_x*2, th + pad_y*2
    x_panel = (W - pw)//2
    y_panel = (H - ph)//2
    x_txt   = x_panel + pad_x
    y_txt   = y_panel + pad_y

    # glass panel
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

    # glow
    glow = Image.new("RGBA", img.size, (0,0,0,0))
    gd   = ImageDraw.Draw(glow)
    gd.text((x_txt, y_txt), t1, font=f1, fill=(255,255,255,255))
    if t2:
        gd.text((x_txt, y_txt+h1+12), t2, font=f2, fill=(255,255,255,255))
    glow = glow.filter(ImageFilter.GaussianBlur(14))
    glow = ImageEnhance.Brightness(glow).enhance(1.2)
    img.alpha_composite(glow)

    # final text
    draw.text((x_txt, y_txt), t1, font=f1, fill=(255,255,255),
              stroke_width=stroke, stroke_fill=(0,0,0))
    if t2:
        draw.text((x_txt, y_txt+h1+12), t2, font=f2,
                  fill=(255,255,255), stroke_width=stroke, stroke_fill=(0,0,0))

    # badge（"Lesson" を表示言語へ）
    bf  = ImageFont.truetype(pick_font(badge_txt), BADGE_SIZE)
    draw.text(BADGE_POS, badge_txt, font=bf,
              fill=(255,255,255), stroke_width=3, stroke_fill=(0,0,0))
    return img

# ------------------------------------------------------ public
def make_thumbnail(topic: str, lang: str, out: Path):
    """
    lang には main.py から第二字幕言語（subs[1]）が渡ってくる想定。
    """
    bg  = _unsplash(topic)
    cap = _caption(topic, lang)
    try:
        badge = translate(BADGE_BASE, lang) or BADGE_BASE
    except Exception:
        badge = BADGE_BASE
    thumb = _draw(bg, cap, badge)
    thumb.convert("RGB").save(out, "JPEG", quality=92)
    logging.info("🖼️  Thumbnail saved → %s", out.name)
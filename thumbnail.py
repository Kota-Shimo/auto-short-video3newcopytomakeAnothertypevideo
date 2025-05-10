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

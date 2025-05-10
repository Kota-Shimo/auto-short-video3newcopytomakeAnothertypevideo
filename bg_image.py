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

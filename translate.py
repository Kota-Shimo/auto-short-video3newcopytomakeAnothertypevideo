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

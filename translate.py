# translate.py
"""GPT翻訳ユーティリティ
- src_lang を明示できるようにして混在を防止
- 言語ガードで "それ bagus." のような混在を自動リトライ
- リトライ/バックオフ/整形を内蔵
"""
from __future__ import annotations

import re, time, random, logging
from typing import Optional
from openai import OpenAI
from config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)

# ---- 言語名マップ（プロンプト用） ----
LANG_NAME = {
    "en": "English", "ja": "Japanese", "ko": "Korean",
    "id": "Indonesian", "pt": "Portuguese", "es": "Spanish",
    "fr": "French", "de": "German", "it": "Italian",
    "zh": "Chinese", "ar": "Arabic",
}

# ---- 文字判定ヘルパ ----
_RE_CJK   = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
_RE_HANG  = re.compile(r"[\uAC00-\uD7AF]")
_RE_LATIN = re.compile(r"[A-Za-z]")

def _looks_like(text: str, lang: str) -> bool:
    if lang == "en":
        # ほぼ ASCII（記号/数字/空白はOK）
        letters = re.sub(r"[^A-Za-z]", "", text)
        return len(letters) > 0 and len(letters) >= int(len(text) * 0.3)
    if lang == "ja":
        return bool(_RE_CJK.search(text))
    if lang == "ko":
        return bool(_RE_HANG.search(text))
    # その他は判定困難 → 常に翻訳
    return False

def _target_guard_ok(text: str, target: str) -> bool:
    """出力がターゲット言語っぽいか簡易チェック"""
    if target == "ja":
        # 日本語は CJK を必ず含み、ラテン文字だらけでない
        if not _RE_CJK.search(text):
            return False
        # ラテン文字比率が高すぎない（英単語混入対策）
        latin = len(_RE_LATIN.findall(text))
        return latin <= max(3, int(len(text) * 0.15))
    if target == "ko":
        return _RE_HANG.search(text) is not None
    else:
        # ラテン系（id/pt/es…）は CJK/Hangul が混ざってないことを確認
        return not (_RE_CJK.search(text) or _RE_HANG.search(text))

def _clean_line(s: str) -> str:
    s = s.replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

MAX_RETRY = 3
BACKOFF   = 1.5

def translate(text: str, target: str, src_lang: Optional[str] = None) -> str:
    """
    text      : 原文
    target    : 'en','ja','ko','id','pt',... ISO-639-1
    src_lang  : 可能なら明示（'ja','en' など）。未指定でも動作。
    戻り値    : 訳文（失敗時は原文を返さず、[XX unavailable] を返す）
    """
    txt = text.strip()
    if not txt:
        return ""

    # 既にターゲットっぽければ翻訳不要
    if _looks_like(txt, target):
        return _clean_line(txt)

    tname = LANG_NAME.get(target, target)
    sname = LANG_NAME.get(src_lang, "Auto") if src_lang else "Auto"

    base_rules = (
        "Translate completely into the target language. "
        "Do not keep any source-language words unless they are proper nouns. "
        "Keep tone natural and suitable for short subtitles. "
        "Return ONLY the translation text."
    )

    def _prompt(strict: bool) -> list[dict]:
        sys = (
            f"You are a professional translator.\n"
            f"Source language: {sname}\nTarget language: {tname}.\n"
            + base_rules
        )
        if strict:
            # 混在が出た時の強制モード
            sys += (
                " This is STRICT mode: output must be 100% in the target language, "
                "no words from the source language."
            )
        return [
            {"role": "system", "content": sys},
            {"role": "user", "content": txt},
        ]

    last_err: Exception | None = None

    # 通常 → ガード失敗時は STRICT で再試行
    for strict in (False, True):
        for attempt in range(1, MAX_RETRY + 1):
            try:
                rsp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=_prompt(strict),
                    temperature=0.2,
                )
                out = _clean_line(rsp.choices[0].message.content)
                if not out:
                    raise RuntimeError("empty response")
                if _target_guard_ok(out, target):
                    return out
                # ガードに失敗 → 次の試行へ
                last_err = RuntimeError(f"language guard failed (-> {target}): {out[:40]}")
            except Exception as e:
                last_err = e
            if attempt < MAX_RETRY:
                time.sleep(BACKOFF + random.random())
        # 通常モードがダメなら STRICT へ、STRICT でもダメなら終了

    logging.warning("Translate error (%s → %s): %s", txt[:40], target, last_err)
    return f"[{target.upper()} unavailable]"
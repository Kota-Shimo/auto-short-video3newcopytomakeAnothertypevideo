"""Generate a two-person *discussion / roleplay* script via GPT-4o with strict monolingual output
   and a light loop-back ending. Seed hook is supported.
"""

from typing import List, Tuple
import re
from openai import OpenAI
from config import OPENAI_API_KEY

openai = OpenAI(api_key=OPENAI_API_KEY)


def _lang_rules(lang: str, topic_hint: str) -> str:
    """
    Strong, language-specific constraints to prevent code-switching.
    We keep them strict only where it commonly goes wrong (e.g., Japanese).
    """
    if lang == "ja":
        # 日本語台本の英語混入・ローマ字混在を強く禁止
        return (
            "This is a Japanese listening script. "
            "Use pure Japanese only. "
            "Do NOT include any English words, romaji (Latin letters), or code-switching. "
            "Ignore any implication that English should appear even if the topic contains '英語'. "
            "Natural Japanese only."
        )
    # 他言語は基本ルールで十分（必要なら同様の強化を追加可能）
    return f"Stay entirely in {lang}. Avoid mixing other languages."


def _sanitize_line(lang: str, text: str) -> str:
    """
    Post-processing to remove stray artifacts that make TTS stumble.
    - ja: remove Latin letters, normalize ellipses, collapse spaces.
    """
    txt = text.strip()

    if lang == "ja":
        # ローマ字・英単語を排除（数字は温存）
        txt = re.sub(r"[A-Za-z]+", "", txt)
        # 三点リーダや…/…を句点へ（TTS安定化）
        txt = txt.replace("...", "。").replace("…", "。")
        # 半角コロン前後の空白を整形
        txt = re.sub(r"\s*:\s*", ": ", txt)
        # 余分な空白を圧縮
        txt = re.sub(r"\s+", " ", txt).strip()

    else:
        # 共通の軽い整形
        txt = txt.replace("…", "...").strip()

    return txt


def make_dialogue(
    topic: str,
    lang: str,
    turns: int = 8,
    seed_phrase: str = ""
) -> List[Tuple[str, str]]:
    """
    - Alice/Bob が交互に話す短い自然会話を生成（2*turns 行）
    - seed_phrase をムード/スタイルのヒントに使う（逐語は避ける）
    - 最終行は話題やフックを軽くリフレインしてループ感を演出
    - 日本語の場合は英語・ローマ字混入を強く禁止 + 出力後にクレンジング
    """
    # トピックのヒント（日本語のみ括弧表記）
    topic_hint = f"「{topic}」" if lang == "ja" else topic

    # 言語固有の厳格ルール
    lang_rules = _lang_rules(lang, topic_hint)

    # GPT へのプロンプト
    prompt = (
        f"You are a native-level {lang.upper()} dialogue writer.\n"
        f"Write a short, natural conversation in {lang} between Alice and Bob.\n\n"
        f"Scene topic: {topic_hint}\n"
        f"Tone reference (seed phrase): \"{seed_phrase}\" (use only as mood/style hint; do not repeat it literally).\n\n"
        "Rules:\n"
        "1) Alternate strictly: Alice, Bob, Alice, Bob...\n"
        f"2) Produce exactly {turns * 2} lines.\n"
        "3) Each line begins with 'Alice:' or 'Bob:' and contains one short, natural sentence.\n"
        f"4) {lang_rules}\n"
        "5) No ellipses (...), no emojis, no bullet points, no stage directions.\n"
        "6) Keep it friendly, realistic, and concise.\n"
        "7) Make the final line subtly echo the main topic or hook to feel loopable.\n"
        "8) Output ONLY the dialogue lines (no explanations).\n"
    )

    rsp = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.45,  # 安定寄り
    )

    raw_lines = rsp.choices[0].message.content.strip().splitlines()

    # "Alice:" or "Bob:" で始まる行のみを抽出
    lines = [l.strip() for l in raw_lines if l.strip().startswith(("Alice:", "Bob:"))]

    # 過剰行はカット・不足は交互に追加
    lines = lines[: turns * 2]
    while len(lines) < turns * 2:
        lines.append("Alice:" if len(lines) % 2 == 0 else "Bob:")

    # "Alice: こんにちは" → ("Alice", "こんにちは")
    parsed: List[Tuple[str, str]] = []
    for ln in lines:
        if ":" in ln:
            spk, txt = ln.split(":", 1)
            txt = _sanitize_line(lang, txt)
            parsed.append((spk.strip(), txt.strip()))
        else:
            # 念のためのフォールバック（ラベルが欠けていた場合）
            spk = "Alice" if len(parsed) % 2 == 0 else "Bob"
            txt = _sanitize_line(lang, ln)
            parsed.append((spk, txt))

    return parsed
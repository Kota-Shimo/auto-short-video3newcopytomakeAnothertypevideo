"""Generate a two-person *discussion / roleplay* script via GPT-4o in any language."""

from typing import List, Tuple
from openai import OpenAI
from config import OPENAI_API_KEY

openai = OpenAI(api_key=OPENAI_API_KEY)

def make_dialogue(topic: str, lang: str, turns: int = 8, seed_phrase: str = "") -> List[Tuple[str, str]]:
    """
    会話形式を自然に生成。
    - seed_phrase があればそれを参考にトーンや冒頭の流れを調整。
    - Alice/Bob が交互に話す、短い自然なやり取り。
    - 最後の1行は冒頭のキーフレーズや話題を軽くリフレインし、
      ループ感を演出する。
    """

    # --- 言語別トピック表示（プロンプト補助用） ---
    if lang == "ja":
        topic_hint = f"「{topic}」"
    else:
        topic_hint = topic

    # --- GPTへ与えるプロンプト ---
    prompt = (
        f"You are a native-level {lang.upper()} dialogue writer.\n"
        f"Write a short, natural conversation in {lang} between Alice and Bob.\n\n"
        f"Scene topic: {topic_hint}\n"
        f"Tone reference (seed phrase): \"{seed_phrase}\" (use only as mood/style hint, don't repeat it literally).\n\n"
        f"Rules:\n"
        f"1. Alternate strictly: Alice, Bob, Alice, Bob...\n"
        f"2. Produce exactly {turns * 2} lines.\n"
        f"3. Each line must begin with 'Alice:' or 'Bob:' followed by one short, natural sentence.\n"
        f"4. Stay entirely in {lang}.\n"
        f"5. Avoid ellipses (...), emojis, or lists.\n"
        f"6. Keep sentences conversational, friendly, and realistic.\n"
        f"7. The final line should softly echo or reference the main topic or the hook idea, "
        f"to make it feel like a loop or callback ending.\n"
        f"8. Output only the dialogue lines (no explanation or notes)."
    )

    rsp = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,  # 安定したトーン
    )

    raw_output = rsp.choices[0].message.content.strip().splitlines()
    lines = [l.strip() for l in raw_output if l.strip().startswith(("Alice:", "Bob:"))]

    # --- フォーマット整形 ---
    parsed: List[Tuple[str, str]] = []
    for ln in lines[: turns * 2]:
        if ":" in ln:
            spk, txt = ln.split(":", 1)
            parsed.append((spk.strip(), txt.strip()))

    # --- 不足補正（安全策）---
    while len(parsed) < turns * 2:
        parsed.append(("Alice" if len(parsed) % 2 == 0 else "Bob", ""))

    return parsed
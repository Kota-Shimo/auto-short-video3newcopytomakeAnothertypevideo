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

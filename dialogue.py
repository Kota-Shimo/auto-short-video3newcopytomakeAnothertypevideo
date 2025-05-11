# dialogue.py
"""Generate a two-person *discussion / debate* script via GPT-4o in any language."""

from openai import OpenAI
from config import OPENAI_API_KEY
from typing import List, Tuple

openai = OpenAI(api_key=OPENAI_API_KEY)

def make_dialogue(topic: str, lang: str, turns: int = 8) -> List[Tuple[str, str]]:
        # ---- 言語別：Aliceの導入セリフ --------------------
    if lang == "ja":
        intro = f"Alice: 今日は「{topic}」について話そう。"
    elif lang == "pt":
        intro = f"Alice: Vamos falar sobre {topic} hoje."
    elif lang == "id":
        intro = f"Alice: Yuk, kita ngobrol soal {topic} hari ini."
    elif lang == "ko":
        intro = f"Alice: 오늘은 {topic}에 대해 이야기해보자."
    else:  # default: English
        intro = f"Alice: Let's talk about {topic} today."

    """
    topic : 議論テーマ
    lang  : 'en', 'ja', 'pt', 'id' … 出力言語コード
    turns : Alice→Bob の往復回数（1 往復 = 2 行）
    戻り値: [(speaker, text), ...]  ※必ず len == turns*2
    """
    prompt = (
        f"Write a natural, podcast-style conversation between Alice and Bob in {lang}.\n"
        f"Topic: \"{topic}\". Exactly {turns - 1} exchanges (start with Bob, since Alice already started).\n\n"
        "• Each line should sound like real spoken language, relaxed and friendly.\n"
        "• Use informal expressions, small reactions, or light humor if appropriate.\n"
        "• Output ONLY the conversation in this strict format:\n"
        "  Alice: <text>\n"
        "  Bob:   <text>\n"
        "• Use ASCII colons (:) with no extra spacing or explanations.\n"
        "• Avoid headings, summaries, or anything besides the dialogue.\n"
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
    # ✅ Aliceの最初のセリフを追加（固定文）
    first_line = f"Alice: Let's talk about {topic} today."
    raw_lines = [intro] + raw_lines

    # ---- 必要数にトリミング / パディング --------------------------
    max_lines = turns * 2                     # 期待行数
    raw_lines = raw_lines[:max_lines]         # 余分をカット

    while len(raw_lines) < max_lines:         # 足りなければ補完
        speaker = "Alice" if len(raw_lines) % 2 == 0 else "Bob"
        raw_lines.append(f"{speaker}: ...")

    # ---- 整形して返却 -------------------------------------------
    return [(spk.strip(), txt.strip())
            for spk, txt in (ln.split(":", 1) for ln in raw_lines)]

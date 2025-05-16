# dialogue.py
"""Generate a two-person *discussion / debate* script via GPT-4o in any language."""

from openai import OpenAI
from config import OPENAI_API_KEY
from typing import List, Tuple

openai = OpenAI(api_key=OPENAI_API_KEY)

def make_dialogue(topic: str, lang: str, turns: int = 8) -> List[Tuple[str, str]]:
    # ---- 言語別：Aliceの導入セリフ ----
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

    # GPTへ渡すプロンプトをより厳密に
    prompt = (
        f"Write a conversation in {lang} between Alice and Bob.\n"
        f"Topic: \"{topic}\". We already have Alice's first line.\n"
        f"Now produce EXACTLY {turns - 1} more exchanges (so total {turns*2} lines),"
        " starting with Bob.\n\n"
        "Formatting rules:\n"
        "1) Output ONLY the dialogue lines, nothing else.\n"
        "2) Each line must begin with 'Alice:' or 'Bob:' (ASCII colon) with no extra spacing.\n"
        "3) Do NOT use ellipses ('...') or bullet points.\n"
        "4) Do NOT include headings, disclaimers, or any text beyond these lines.\n"
        "5) Keep it casual and natural.\n"
        "\nExample of correct format:\n"
        "Alice: Hello!\n"
        "Bob: Hey, how are you?\n"
        "Alice: I'm good!\n"
        "Bob: Glad to hear it.\n"
    )

    rsp = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,  # やや下げて余計な創作を抑える
    )

    # GPTの応答から "Alice:" / "Bob:" で始まる行だけを抜く
    raw_lines = [
        l.strip() for l in rsp.choices[0].message.content.splitlines()
        if l.strip().startswith(("Alice:", "Bob:"))
    ]

    # GPTには「Aliceの最初のセリフは既にある」と伝えているので、
    # ここで自分で intro を先頭に加える
    raw_lines = [intro] + raw_lines

    # ---- 必要数にトリミング / パディング --------------------------
    max_lines = turns * 2
    raw_lines = raw_lines[:max_lines]

# パディングはしない。足りない行はそのまま無視する。

# 整形して返却
    return [(spk.strip(), txt.strip())
        for spk, txt in (ln.split(":", 1) for ln in raw_lines)]

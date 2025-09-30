# dialogue.py
"""Generate a two-person *discussion / debate* script via GPT-4o in any language."""

from typing import List, Tuple
from openai import OpenAI
from config import OPENAI_API_KEY

openai = OpenAI(api_key=OPENAI_API_KEY)

def make_dialogue(topic: str, lang: str, turns: int = 8) -> List[Tuple[str, str]]:
    """
    自前で Alice の1行目（イントロ）を確定 → GPT には
    ・Bob から開始
    ・交互に会話
    ・合計で (2*turns - 1) 行 を生成
    を要求して、最終的に 2*turns 行に整える。
    """

    # ---- 言語別：Alice の導入セリフ（topic は main 側で音声言語に翻訳済み前提）----
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

    # ---- GPT へのプロンプト ----
    # 自前イントロを固定しつつ、Bob から (2*turns - 1) 行を生成させる
    expected_gpt_lines = turns * 2 - 1  # Alice 1行は自前 → 残りはGPT
    prompt = (
        f"You are a professional {lang.upper()} speaker. "
        f"Write a conversation EXCLUSIVELY in {lang} between Alice and Bob.\n\n"
        f"Topic: \"{topic}\".\n"
        f"Use the following FIRST line from Alice exactly as given:\n"
        f"{intro}\n\n"
        f"Then continue the conversation starting with Bob and strictly alternate speakers. "
        f"Produce EXACTLY {expected_gpt_lines} lines (no more, no fewer).\n\n"
        "Formatting rules:\n"
        f"1) The entire conversation MUST be in {lang} only. Do not use any other language.\n"
        "2) Output ONLY the dialogue lines, no headings or explanations.\n"
        "3) Each line must begin with 'Alice:' or 'Bob:' (ASCII colon) with no extra spacing.\n"
        "4) Do NOT use ellipses ('...') or bullet points.\n"
        "5) Keep it casual and natural; keep each line concise.\n"
    )

    rsp = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,  # 言語逸脱を抑制
    )

    # GPT 応答から "Alice:" / "Bob:" で始まる行のみ抽出
    lines_from_gpt = [
        l.strip() for l in rsp.choices[0].message.content.splitlines()
        if l.strip().startswith(("Alice:", "Bob:"))
    ]

    # 先頭に自前イントロを追加 → 最終 2*turns 行に丸める
    raw_lines = [intro] + lines_from_gpt
    max_lines = turns * 2
    raw_lines = raw_lines[:max_lines]

    # "Alice: こんにちは" → ("Alice", "こんにちは") に整形
    parsed: List[Tuple[str, str]] = []
    for ln in raw_lines:
        if ":" in ln:
            spk, txt = ln.split(":", 1)
            parsed.append((spk.strip(), txt.strip()))

    return parsed
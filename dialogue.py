# dialogue.py
"""Generate a two-person *discussion / debate* script via GPT-4o in any language."""

from typing import List, Tuple
from openai import OpenAI
from config import OPENAI_API_KEY

openai = OpenAI(api_key=OPENAI_API_KEY)

def make_dialogue(topic: str, lang: str, turns: int = 8) -> List[Tuple[str, str]]:
    """
    Alice の最初の1行目は自前で固定。
    GPT には Bob から開始し、交互に会話を生成させる。
    合計 (2*turns) 行になるよう制御する。
    """

    # ---- 言語別：Alice の導入セリフ（topic は main 側から渡される）----
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
    expected_gpt_lines = turns * 2 - 1  # Aliceの1行は固定 → 残りをGPTで生成
    prompt = (
        f"You are a professional {lang.upper()} speaker. "
        f"Write a conversation EXCLUSIVELY in {lang} between Alice and Bob.\n\n"
        f"Topic: \"{topic}\".\n"
        f"The first line is already fixed:\n{intro}\n\n"
        f"Continue the dialogue starting with Bob, alternating strictly Alice/Bob. "
        f"Produce EXACTLY {expected_gpt_lines} lines (no more, no fewer).\n\n"
        "Formatting rules:\n"
        f"1) The entire conversation MUST be in {lang} only. Do not use any other language.\n"
        "2) Output ONLY the dialogue lines, no headings or explanations.\n"
        "3) Each line must begin with 'Alice:' or 'Bob:' (ASCII colon).\n"
        "4) Do NOT use ellipses ('...') or bullet points.\n"
        "5) Keep it casual and natural, each line concise.\n"
    )

    rsp = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,  # 言語逸脱を抑える
    )

    # GPT 応答から "Alice:" / "Bob:" で始まる行のみ抽出
    lines_from_gpt = [
        l.strip() for l in rsp.choices[0].message.content.splitlines()
        if l.strip().startswith(("Alice:", "Bob:"))
    ]

    # もし GPT が間違って Alice の冒頭を含んでしまった場合 → 除外
    if lines_from_gpt and lines_from_gpt[0].startswith("Alice:"):
        lines_from_gpt = lines_from_gpt[1:]

    # 最終行リスト: イントロ + GPT生成
    raw_lines = [intro] + lines_from_gpt

    # 行数調整（多すぎる場合はカット、足りない場合はそのまま）
    max_lines = turns * 2
    raw_lines = raw_lines[:max_lines]

    # "Alice: こんにちは" → ("Alice", "こんにちは") に整形
    parsed: List[Tuple[str, str]] = []
    for ln in raw_lines:
        if ":" in ln:
            spk, txt = ln.split(":", 1)
            parsed.append((spk.strip(), txt.strip()))

    return parsed
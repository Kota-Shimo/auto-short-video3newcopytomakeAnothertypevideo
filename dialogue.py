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

    # ❗ GPT へのプロンプトをより強力に「選択言語だけを使う」よう指示
    #   例: 日本語にしたい場合は "the entire conversation must be in Japanese" と明示
    prompt = (
        f"You are a professional {lang.upper()} speaker. "
        f"Write a conversation EXCLUSIVELY in {lang} between Alice and Bob.\n\n"
        f"Topic: \"{topic}\". We already have the first line from Alice:\n"
        f"  {intro}\n"
        f"Now produce EXACTLY {turns - 1} more exchanges (so total {turns*2} lines) "
        "starting with Bob.\n\n"
        "Formatting rules:\n"
        "1) The entire conversation MUST be in {lang} only. Do not use any other language.\n"
        "2) Output ONLY the dialogue lines, no headings or explanations.\n"
        "3) Each line must begin with 'Alice:' or 'Bob:' (ASCII colon) with no extra spacing.\n"
        "4) Do NOT use ellipses ('...') or bullet points.\n"
        "5) Keep it casual and natural.\n"
        "\nExample of correct format:\n"
        "Alice: こんにちは、元気？\n"
        "Bob: うん、大丈夫だよ。\n"
        "Alice: じゃあ早速はじめようか。\n"
        "Bob: そうしよう！\n"
    )

    rsp = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,  # さらに少し低めにして、言語逸脱を抑える
    )

    # GPTの応答から "Alice:" / "Bob:" で始まる行だけを抽出
    raw_lines = [
        l.strip() for l in rsp.choices[0].message.content.splitlines()
        if l.strip().startswith(("Alice:", "Bob:"))
    ]

    # 先頭に自前イントロを追加
    raw_lines = [intro] + raw_lines

    # 必要行数にトリミング
    max_lines = turns * 2
    raw_lines = raw_lines[:max_lines]

    # 整形して返却
    # 例: "Alice: こんにちは" → ("Alice", "こんにちは")
    return [
        (spk.strip(), txt.strip())
        for spk, txt in (ln.split(":", 1) for ln in raw_lines)
    ]
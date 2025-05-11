# topic_picker.py
"""
Pick TODAY’s podcast/video topic.

1. できれば GPT-4o で “今日っぽい” キーワードを 1 行だけ取得  
2. API 呼び出しが失敗したら SEED_TOPICS からランダムでフォールバック
"""

import random
import datetime
import os
import openai
import re

openai.api_key = os.getenv("OPENAI_API_KEY")

# ── フォールバック用プリセット ─────────────────────────
SEED_TOPICS: list[str] = [
    # Tech & Science
    "AI ethics", "quantum computing", "space exploration",
    # Lifestyle & Culture
    "sustainable travel", "mindfulness", "plant-based diets",
    # Arts
    "classical music", "digital illustration", "street photography",
]

# ────────────────────────────────────────────────────────
def _clean(raw: str) -> str:
    """
    GPT 応答に余計な「Sure, here is…」などが混ざっても
    先頭行だけを抜き取り、引用符・句読点を削ぐ。
    """
    first_line = raw.strip().splitlines()[0]
    topic = re.sub(r'^[\"“”\'\-•\s]*', "", first_line)   # 先頭の記号/空白
    topic = re.sub(r'[\"“”\'\s]*$', "", topic)           # 末尾の記号/空白
    return topic


def pick() -> str:
    """Return one short topic phrase (ASCII/UTF-8)."""
    today = datetime.date.today().isoformat()

    prompt = (
        f"Today is {today}. Give me ONE short, trending topic idea for a"
        " 60-90-second educational video. **Return ONLY the topic phrase** –"
        " no explanations, no punctuation, no quotation marks."
    )

    try:
        rsp = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            timeout=20,
        )
        topic = _clean(rsp.choices[0].message.content)
        return topic or random.choice(SEED_TOPICS)

    except Exception as e:  # ネットワーク・キー無効など
        # ログに残す場合は logging を使う
        return random.choice(SEED_TOPICS)


if __name__ == "__main__":
    print(pick())

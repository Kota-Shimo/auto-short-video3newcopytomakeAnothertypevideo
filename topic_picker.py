# topic_picker.py
"""
Pick TODAY’s podcast/video topic.

- まず GPT-4o に「今日向けの語学学習シーン」を1行だけリクエスト
- API 呼び出しが失敗したら SEED_TOPICS からランダムでフォールバック
"""

import random
import datetime
import os
import openai
import re

openai.api_key = os.getenv("OPENAI_API_KEY")

# ── フォールバック用プリセット（実用シーン固定） ───────────────
SEED_TOPICS: list[str] = [
    # ホテル英語
    "ホテル英語 - チェックイン",
    "ホテル英語 - 朝食の案内",
    "ホテル英語 - 部屋の設備説明",
    "ホテル英語 - チェックアウト",

    # 空港英会話
    "空港英会話 - チェックインカウンター",
    "空港英会話 - 保安検査",
    "空港英会話 - 搭乗口での案内",
    "空港英会話 - 機内でのやりとり",

    # レストラン英語
    "レストラン英語 - 入店と席案内",
    "レストラン英語 - 注文",
    "レストラン英語 - 料理の説明",
    "レストラン英語 - 会計",
]

# ────────────────────────────────────────
def _clean(raw: str) -> str:
    """
    GPT 応答に余計な文が混ざっても
    先頭行だけを抜き取り、引用符や記号を削る。
    """
    first_line = raw.strip().splitlines()[0]
    topic = re.sub(r'^[\"“”\'\-•\s]*', "", first_line)   # 先頭
    topic = re.sub(r'[\"“”\'\s]*$', "", topic)           # 末尾
    return topic


def pick() -> str:
    """Return one topic phrase like 'ホテル英語 - チェックイン'."""
    today = datetime.date.today().isoformat()

    prompt = (
        f"Today is {today}. Suggest ONE short, practical topic for a language-learning video.\n"
        "It must be in Japanese, format: '<大テーマ> - <具体シーン>'.\n"
        "Examples: 'ホテル英語 - チェックイン', '空港英会話 - 保安検査'.\n"
        "Return ONLY the phrase, no punctuation or quotes."
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

    except Exception:
        return random.choice(SEED_TOPICS)


if __name__ == "__main__":
    print(pick())
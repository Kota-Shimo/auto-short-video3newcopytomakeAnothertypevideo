"""
topic_picker.py – Pick an optimal English-learning topic for today’s video.
新仕様:
- GPT に「英語学習者向けの今日の最適トピック」を考えさせる
- カテゴリや目的を含む JSON 出力
- 失敗時は SEED_TOPICS からランダムにフォールバック
"""

import random
import datetime
import os
import re
import json
from openai import OpenAI

GPT = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ── フォールバック用プリセット ───────────────
SEED_TOPICS = [
    {"topic": "ホテル英語 - チェックイン", "category": "旅行", "focus": "基本表現"},
    {"topic": "レストラン英語 - 注文", "category": "食事", "focus": "会話練習"},
    {"topic": "空港英会話 - 保安検査", "category": "旅行", "focus": "質問応答"},
    {"topic": "仕事で使う英語 - 自己紹介", "category": "ビジネス", "focus": "スモールトーク"},
    {"topic": "旅行英会話 - 道を尋ねる", "category": "日常", "focus": "実践会話"},
    {"topic": "接客英語 - おすすめを伝える", "category": "仕事", "focus": "接客応対"},
]

def _clean(raw: str) -> str:
    """GPT応答に余計な文が混ざっても、先頭行のみ抜き出す。"""
    first_line = raw.strip().splitlines()[0]
    topic = re.sub(r'^[\"“”\'\-•\s]*', "", first_line)
    topic = re.sub(r'[\"“”\'\s]*$', "", topic)
    return topic.strip()

def pick() -> dict:
    """
    Return a dict like:
    {
      "topic": "ホテル英語 - チェックイン",
      "category": "旅行",
      "focus": "実践会話",
      "reason": "ホテルでのチェックイン会話は最も頻出だから"
    }
    """
    today = datetime.date.today().isoformat()

    prompt = f"""
You are an English-teaching content strategist.
Today is {today}.
Suggest ONE concise, useful topic for an English-learning video (for beginners to intermediates).
Return JSON like this:

{{
  "topic": "<in Japanese, e.g. ホテル英語 - チェックイン>",
  "category": "<broad domain: 旅行 / ビジネス / 日常 / 文法 / 発音>",
  "focus": "<learning goal: 会話練習 / 発音 / ボキャブラリー / 文法 / 表現>",
  "reason": "<1 short reason why this is a good choice>"
}}

Rules:
- Topic must be in Japanese.
- Keep it short and natural.
- Return ONLY valid JSON.
"""

    try:
        rsp = GPT.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            response_format={"type": "json_object"},
        )
        data = json.loads(rsp.choices[0].message.content)
        if not data.get("topic"):
            raise ValueError("Empty GPT output")
        return data

    except Exception as e:
        # GPTが落ちた場合はランダムフォールバック
        fallback = random.choice(SEED_TOPICS)
        fallback["reason"] = "GPT fallback"
        return fallback

if __name__ == "__main__":
    print(json.dumps(pick(), ensure_ascii=False, indent=2))
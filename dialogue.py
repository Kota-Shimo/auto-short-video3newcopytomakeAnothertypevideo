"""
dialogue.py – GPT により英語学習向けショート台本を生成。
構成: Hook（導入）→ Main（説明）→ Callback（締め）
"""

import json
from typing import Dict
from openai import OpenAI
from config import OPENAI_API_KEY

GPT = OpenAI(api_key=OPENAI_API_KEY)

def make_dialogue(topic: str, lang: str, turns: int = 8, seed_phrase: str = "") -> Dict:
    """
    Generate a structured short-form learning script:
      - hook: attention-grabbing start
      - main: explanation or examples (3–5 short lines)
      - callback: closing line that links back to the hook
    Returns a dict:
    {
      "title": "string",
      "segments": [
        {"role": "hook", "text": "..."},
        {"role": "main", "text": "..."},
        {"role": "callback", "text": "..."}
      ]
    }
    """

    # --- Prompt設計 ---
    prompt = f"""
You are a professional {lang.upper()} scriptwriter for YouTube Shorts.
Create a short (≤45 seconds) educational video script for language learners.

Topic: "{topic}"

Structure:
1. Hook — Start with an engaging or surprising line (1 short sentence).
2. Main — Explain the phrase or give 2–3 short conversational examples.
3. Callback — End with a satisfying line that connects back to the Hook.

Requirements:
- Entire script must be in {lang}.
- Keep each line under 12 words for readability.
- Natural tone, emotionally engaging, slightly conversational.
- Do NOT include any explanations outside the dialogue.
- Return ONLY a JSON object with this structure:

{{
  "title": "string",
  "segments": [
    {{"role": "hook", "text": "..."}},
    {{"role": "main", "text": "..."}},
    {{"role": "main", "text": "..."}},
    {{"role": "callback", "text": "..."}}
  ]
}}
"""

    rsp = GPT.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6,
        response_format={"type": "json_object"},
    )

    try:
        data = json.loads(rsp.choices[0].message.content)
    except Exception:
        # GPTの出力がJSONでない場合の安全フォールバック
        data = {
            "title": topic,
            "segments": [
                {"role": "hook", "text": seed_phrase or f"Let's talk about {topic}."},
                {"role": "main", "text": f"This phrase means '{topic}' in daily life."},
                {"role": "callback", "text": "Now you can use it naturally!"},
            ],
        }

    # --- 後処理: 構造正規化 ---
    if "segments" not in data:
        data = {
            "title": topic,
            "segments": [
                {"role": "hook", "text": seed_phrase or f"Let's talk about {topic}."},
                {"role": "main", "text": f"This phrase means '{topic}' in daily life."},
                {"role": "callback", "text": "Now you can use it naturally!"},
            ],
        }

    return data
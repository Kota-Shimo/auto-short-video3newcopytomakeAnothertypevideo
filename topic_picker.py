# topic_picker.py
"""
Pick TODAY’s podcast/video topic.

- まず GPT-4o に “自然な日本語の会話シーン名” を 1 行だけリクエスト
- 応答が旧形式（「<大テーマ> - <具体シーン>」や「英語/英会話」を含む）でも
  自動的に “ホテルでのチェックイン会話” のような自然表現へ正規化
- API 呼び出しが失敗したら SEED_TOPICS からランダムでフォールバック
"""

import random
import datetime
import os
import openai
import re

openai.api_key = os.getenv("OPENAI_API_KEY")

# ── フォールバック用プリセット（最初から自然な日本語） ───────────────
SEED_TOPICS: list[str] = [
    "ホテルでのチェックイン会話",
    "ホテルでの朝食案内",
    "ホテルでの部屋設備の説明",
    "ホテルでのチェックアウト会話",

    "空港でのチェックイン会話",
    "空港での保安検査のやりとり",
    "空港での搭乗口アナウンスの受け答え",
    "機内でのやりとり",

    "レストランでの入店と席案内",
    "レストランでの注文会話",
    "料理の説明を聞く会話",
    "レストランでの会計会話",
]

# ────────────────────────────────────────
# 正規化ユーティリティ
# ────────────────────────────────────────

# 大テーマの置換表（「◯◯英語/英会話」→「◯◯での」等）
THEME_MAP = {
    "ホテル英語": "ホテルでの",
    "空港英会話": "空港での",
    "空港英語": "空港での",
    "レストラン英語": "レストランでの",
    "旅行英会話": "旅行中の",
    "接客英語": "接客の",
    "仕事で使う英語": "仕事での",
    "ビジネス英語": "ビジネスでの",
}

# 「の会話」を付けずに自然な名詞句で終わらせたいキーワード
NO_SUFFIX_KEYWORDS = [
    "会話", "やりとり", "案内", "説明", "確認", "手続き", "質問", "受け答え",
    "問い合わせ", "オーダー", "予約", "対応", "注意点", "ポイント"
]

def _clean_line(raw: str) -> str:
    """先頭行を取り、両端の引用符や記号を除去"""
    first = raw.strip().splitlines()[0]
    t = re.sub(r'^[\s"“”\'\-•・]+', "", first)
    t = re.sub(r'[\s"“”\']+$', "", t)
    t = re.sub(r'\s+', " ", t).strip()
    return t

def _needs_suffix(scene: str) -> bool:
    return not any(k in scene for k in NO_SUFFIX_KEYWORDS)

def _normalize_hyphen_form(s: str) -> str:
    """
    「<大テーマ>(英語|英会話)? - <具体シーン>」→「<場所/文脈> <具体シーン>(の会話)」
    例: "ホテル英語 - チェックイン" → "ホテルでの チェックイン会話"
    """
    # 例: 「ホテル英語 - チェックイン」「空港英会話-保安検査」などに対応
    m = re.match(r'^\s*(.+?)\s*(?:英語|英会話)?\s*-\s*(.+?)\s*$', s)
    if not m:
        return s  # ハイフン形式でない → そのまま

    theme, scene = m.group(1), m.group(2)
    # テーマ正規化
    for k, v in THEME_MAP.items():
        if k in theme:
            theme = theme.replace(k, v)
            break
    # テーマに「での/中の/の」で終わらない場合の軽い保険
    if not re.search(r'(での|中の|の)$', theme):
        theme = theme + "での"

    # 余計な助詞連続を軽く整形（例: 「でのでの」など）
    theme = re.sub(r'(での)+', 'での', theme)
    theme = re.sub(r'(のの)+', 'の', theme)

    # 「の会話」をつけるか判断
    if _needs_suffix(scene):
        scene_out = f"{scene}の会話"
    else:
        scene_out = scene

    topic = f"{theme} {scene_out}"
    return re.sub(r'\s+', " ", topic).strip()

def _normalize(topic: str) -> str:
    """
    1) ハイフン形式なら自然表現へ変換
    2) 「英語/英会話」を含む旧表現をテーマ変換
    3) 冗長な空白や記号を整理
    """
    t = topic

    # 1) ハイフン形式を優先的に正規化
    if " - " in t or "-" in t:
        t = _normalize_hyphen_form(t)

    # 2) テーマ単体が残っているケースへも対応
    for k, v in THEME_MAP.items():
        t = t.replace(k, v)

    # 3) 末尾が不自然なら簡易補正（例: 「ホテルでのチェックイン」→「ホテルでのチェックイン会話」）
    if re.search(r'(での|中の|の)\s*$', t):
        t = t.rstrip(" の")
    # シーンが短い名詞のみで終わる場合、自然に会話へ落とす
    if not any(k in t for k in NO_SUFFIX_KEYWORDS):
        # 「〜での ◯◯」の形なら「〜での ◯◯会話」へ
        m2 = re.match(r'^(.*での)\s+(.+)$', t)
        if m2:
            prefix, scene = m2.group(1), m2.group(2)
            # 既に十分自然なら維持（例: 機内でのやりとり）
            if _needs_suffix(scene):
                t = f"{prefix} {scene}の会話"

    # 仕上げの整形
    t = re.sub(r'\s+', " ", t).strip()
    return t

# ────────────────────────────────────────
def pick() -> str:
    """自然な日本語の会話シーントピックを返す。"""
    today = datetime.date.today().isoformat()

    prompt = (
        f"Today is {today}. "
        "日本語で、語学学習向けの“自然な会話シーン名”を1つだけ提案してください。"
        "例:『ホテルでのチェックイン会話』『空港での保安検査のやりとり』『レストランでの注文会話』。"
        "15〜20文字程度を目安。句読点や引用符は不要。"
        "返答はそのフレーズ1行のみ。"
    )

    try:
        rsp = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            timeout=20,
        )
        raw = _clean_line(rsp.choices[0].message.content)
        topic = _normalize(raw)
        # 文字化けや英語混入の簡易ガード
        if not topic or re.search(r'[A-Za-z]', topic):
            return random.choice(SEED_TOPICS)
        return topic

    except Exception:
        return random.choice(SEED_TOPICS)


if __name__ == "__main__":
    print(pick())
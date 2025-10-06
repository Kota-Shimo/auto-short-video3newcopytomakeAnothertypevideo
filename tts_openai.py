"""OpenAI TTS wrapper – language-aware & two-speaker support."""

import re
from pathlib import Path
from openai import OpenAI
from config import OPENAI_API_KEY, VOICE_MAP

client = OpenAI(api_key=OPENAI_API_KEY)

# フォールバック用（言語が VOICE_MAP に無い場合）
FALLBACK_VOICES = ("alloy", "echo")  # (Alice, Bob)


def _clean_for_tts(text: str, lang: str) -> str:
    """
    音声合成前にテキストを整形：
    - 話者名「Alice:」「Bob:」などを削除
    - 不要な英語記号や半端な句読点を除去
    - 空白や改行を整理
    - 日本語TTSの誤読を防ぐため、英単語を一部カタカナっぽく分離
    """
    t = re.sub(r"^[A-Za-z]+:\s*", "", text)  # Alice: など削除
    t = re.sub(r"\s+", " ", t).strip()        # 改行・余白整理

    # 言語別クリーンアップ（日本語用に特別処理）
    if lang == "ja":
        # 英単語を無理に読ませないように除去またはスペース化
        t = re.sub(r"[A-Za-z]+", "", t)
        # 記号や不要な文字を除去
        t = re.sub(r"[#\"'※＊*~`]", "", t)
        t = re.sub(r"\s+", " ", t).strip()

    return t or "。"


def speak(lang: str, speaker: str, text: str, out_path: Path):
    """
    lang     : 'en', 'ja', 'pt', 'id' など
    speaker  : 'Alice' / 'Bob' で声を切替
    text     : セリフ
    out_path : 書き出し先 .mp3
    """
    # ✅ 音声化前にクリーンアップ
    clean_text = _clean_for_tts(text, lang)

    v_a, v_b = VOICE_MAP.get(lang, FALLBACK_VOICES)
    voice_id = v_a if speaker.lower() == "alice" else v_b

    resp = client.audio.speech.create(
        model="tts-1",          # 高音質は "tts-1-hd"
        voice=voice_id,
        input=clean_text
    )
    out_path.write_bytes(resp.content)
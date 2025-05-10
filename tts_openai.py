# tts_openai.py
"""OpenAI TTS wrapper – language-aware & two-speaker support."""

from pathlib import Path
from openai import OpenAI
from config import OPENAI_API_KEY, VOICE_MAP

client = OpenAI(api_key=OPENAI_API_KEY)

# フォールバック用（言語が VOICE_MAP に無い場合）
FALLBACK_VOICES = ("alloy", "echo")  # (Alice, Bob)

def speak(lang: str, speaker: str, text: str, out_path: Path):
    """
    lang     : 'en', 'ja', 'pt', 'id' など
    speaker  : 'Alice' / 'Bob' で声を切替
    text     : セリフ
    out_path : 書き出し先 .mp3
    """
    v_a, v_b = VOICE_MAP.get(lang, FALLBACK_VOICES)
    voice_id = v_a if speaker.lower() == "alice" else v_b

    resp = client.audio.speech.create(
        model="tts-1",          # 高音質は "tts-1-hd"
        voice=voice_id,
        input=text
    )
    out_path.write_bytes(resp.content)

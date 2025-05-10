from pathlib import Path
from elevenlabs import generate as tts_gen
from config import ELEVEN_API_KEY, VOICE_A, VOICE_B

# -------------------------------------------------
# 公開サンプルの音声 ID（無料枠で利用可）
# 使いたい声があればここか .env で上書きしてください
VOICE_MAP = {
    "Rachel": "21m00Tcm4TlvDq8ikWAM",
    "Adam":   "OmEnGXU7trwJsZ3jMPl8",
}
# -------------------------------------------------

def line_to_voice(speaker: str, text: str, out: Path):
    """
    speaker : 'Alice' または 'Bob' など
    text    : セリフ
    out     : mp3 書き出し先 Path
    """
    # 1) .env の VOICE_A / VOICE_B を最優先
    if speaker.lower() == "alice":
        vid = VOICE_A or VOICE_MAP["Rachel"]
    else:
        vid = VOICE_B or VOICE_MAP["Adam"]

    # 2) fallback — 万一 ID が空なら公開 ID を使用
    if not vid:
        vid = VOICE_MAP["Rachel"]

    # 3) ElevenLabs にリクエスト
    if not ELEVEN_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY が設定されていません。")

    out.write_bytes(
        tts_gen(
            api_key=ELEVEN_API_KEY,
            text=text,
            voice=vid,
        )
    )

# audio_fx.py – “良いマイク風” (deesser 非依存バージョン)
import subprocess
import shutil
from pathlib import Path

# -----------------------------------------------------------
# FILTER chain
#   1) highpass 60 Hz         : 空調/机振動カット
#   2) lowpass  10.5 kHz      : モスキートノイズ抑制
#   3) presence EQ 4 kHz +3dB : 明瞭度
#   4) soft de-ess  8 kHz −2dB: 歯擦音をやや抑える (simple EQ)
#   5) soft compressor        : ratio 2:1 で自然に
#   6) loudnorm (-16 LUFS)    : ポッドキャスト標準ラウドネス
FILTER = (
    "highpass=f=60,"
    "lowpass=f=10500,"
    "equalizer=f=4000:width_type=h:width=150:g=3,"
    "equalizer=f=8000:width_type=h:width=300:g=-2,"
    "acompressor=threshold=-18dB:ratio=2:knee=2:attack=15:release=200,"
    "loudnorm=I=-16:TP=-1.5:LRA=11"
)
# -----------------------------------------------------------

def enhance(in_mp3: Path, out_mp3: Path):
    """
    in_mp3  : 入力 mp3
    out_mp3 : 整音後 mp3
    """
    # ffmpeg バイナリ確認
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg が見つかりません。PATH を確認してください。")

    # 入力存在チェック（早期に原因を出す）
    in_mp3 = Path(in_mp3)
    out_mp3 = Path(out_mp3)

    if not in_mp3.exists():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {in_mp3}")

    # 出力フォルダを安全に作成
    out_mp3.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner", "-nostdin", "-loglevel", "error",  # エラーメッセージのみ簡潔に
        "-i", str(in_mp3),
        "-af", FILTER,
        "-ar", "48000",  # 48 kHz に統一（必要に応じて 44100）
        str(out_mp3)
    ]

    # 実行コマンドを出力（後で再現しやすい）
    print("▶ FFmpeg cmd:", " ".join(cmd))

    # 標準出力・エラーをキャプチャして、失敗時に丸ごと表示
    proc = subprocess.run(cmd, text=True, capture_output=True)

    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        out = (proc.stdout or "").strip()
        raise RuntimeError(
            f"FFmpeg failed (exit code {proc.returncode}).\n"
            f"---- STDERR ----\n{err}\n"
            f"---- STDOUT ----\n{out}\n"
            "----------------\n"
            "※ 上のエラー出力を貼ってくれれば、原因を特定して修正案を出します。"
        )
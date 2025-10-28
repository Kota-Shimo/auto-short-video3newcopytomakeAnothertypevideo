# audio_fx.py – “良いマイク風” (deesser 非依存バージョン)
import subprocess
import shutil
from pathlib import Path

# ==== 例外クラス（main.py から import される）====
class SmallAudioError(RuntimeError):
    """入力音源が小さすぎる/壊れている場合に投げる例外。"""
    pass

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

def _require_bin(name: str):
    if not shutil.which(name):
        raise RuntimeError(f"{name} が見つかりません。PATH を確認してください。")

def _ffprobe_duration_and_format(in_file: Path) -> tuple[float, str]:
    """
    ffprobe でフォーマット名と持続時間(秒)を取得。
    失敗時は (-1.0, "") を返す。
    """
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration,format_name",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(in_file)
        ]
        # 出力: 1行目=format_name, 2行目=duration
        res = subprocess.run(cmd, text=True, capture_output=True)
        if res.returncode != 0:
            return -1.0, ""
        lines = [x.strip() for x in res.stdout.splitlines() if x.strip()]
        if len(lines) < 2:
            return -1.0, ""
        fmt = lines[0]
        try:
            dur = float(lines[1])
        except ValueError:
            dur = -1.0
        return dur, fmt
    except Exception:
        return -1.0, ""

def enhance(in_mp3: Path, out_mp3: Path):
    """
    in_mp3  : 入力 mp3
    out_mp3 : 整音後 mp3
    """
    _require_bin("ffmpeg")
    _require_bin("ffprobe")

    in_mp3 = Path(in_mp3)
    out_mp3 = Path(out_mp3)

    # 入力ファイルの存在とサイズを早期チェック
    if not in_mp3.exists():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {in_mp3}")
    size = in_mp3.stat().st_size
    if size < 2048:
        # ← 小さすぎ/未完ファイルは SmallAudioError に分類
        raise SmallAudioError(
            f"入力MP3のサイズが小さすぎます（{size} bytes）。"
            " TTS 生成が未完了/失敗の可能性。上流の生成処理を確認してください。"
        )

    # ffprobe で形式と長さを確認
    dur, fmt = _ffprobe_duration_and_format(in_mp3)
    if dur < 0 or dur < 0.2:
        raise SmallAudioError(
            "入力MP3が壊れている/極端に短い可能性があります。\n"
            f"- ffprobe format: {fmt or '未知'}\n"
            f"- ffprobe duration: {dur:.3f} sec\n"
            "※ 典型例: ID3タグのみで音声フレームが無い、TTS失敗で空ファイル、保存前に読み出し等。"
        )

    # 出力フォルダを安全に作成
    out_mp3.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner", "-nostdin", "-loglevel", "error",
        "-i", str(in_mp3),
        "-af", FILTER,
        "-ar", "48000",
        str(out_mp3)
    ]

    print("▶ FFmpeg cmd:", " ".join(cmd))
    proc = subprocess.run(cmd, text=True, capture_output=True)

    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        out = (proc.stdout or "").strip()
        raise RuntimeError(
            f"FFmpeg failed (exit code {proc.returncode}).\n"
            f"---- STDERR ----\n{err}\n"
            f"---- STDOUT ----\n{out}\n"
            "----------------\n"
            "よくある原因:\n"
            " 1) 入力MP3が未完/破損（ID3のみ等）\n"
            " 2) 実体がMP3でない（拡張子だけmp3）\n"
            " 3) 出力先パスの権限/存在\n"
            "→ まず上の ffprobe 情報と STDERR をチェックしてください。"
        )
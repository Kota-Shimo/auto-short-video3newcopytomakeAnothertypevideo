#!/usr/bin/env python3
"""
長尺 lines.json + full.mp3 + 背景 → チャンク分割して mp4 を作成し
最後に ffmpeg concat で 1 本に結合する。

usage:
  python chunk_builder.py temp/lines.json temp/full.mp3 temp/bg.png \
        --chunk 60 --rows 2 --out output/final_long.mp4
"""
from pathlib import Path
import argparse, json, subprocess, tempfile, shutil
from os import makedirs

from subtitle_video import build_video            # 既存関数

# ──────────── CLI ─────────────────────
ap = argparse.ArgumentParser()
ap.add_argument("lines_json")
ap.add_argument("full_mp3")
ap.add_argument("bg_png")
ap.add_argument("--out",        default="output/final.mp4")
ap.add_argument("--chunk", type=int, default=40, help="1 チャンクあたりの行数")
ap.add_argument("--rows",  type=int, default=2,  help="字幕段数")
ap.add_argument("--fsize-top", type=int, default=None)
ap.add_argument("--fsize-bot", type=int, default=None)
args = ap.parse_args()

SCRIPT     = Path(args.lines_json)
FULL_MP3   = Path(args.full_mp3)
BG_PNG     = Path(args.bg_png)
FINAL_MP4  = Path(args.out)
LINES_PER  = args.chunk
ROWS       = args.rows

if not (SCRIPT.exists() and FULL_MP3.exists() and BG_PNG.exists()):
    raise SystemExit("❌ 必要なファイルが見つかりません")

# 出力先ディレクトリを用意
makedirs(FINAL_MP4.parent, exist_ok=True)

# ──────────── 準備 ─────────────────────
TEMP = Path(tempfile.mkdtemp(prefix="chunks_"))
print("🗂️  temp dir =", TEMP)

lines = json.loads(SCRIPT.read_text())            # [[spk,line1,line2,dur]...]
parts = [lines[i:i+LINES_PER] for i in range(0, len(lines), LINES_PER)]

# full.mp3 を duration 情報でカットして各チャンクに対応させる
durations  = [row[-1] for row in lines]           # 各行の秒数
cumulative = [0]
for d in durations:
    cumulative.append(cumulative[-1] + d)         # 累積時間

part_files = []
for idx, chunk in enumerate(parts):
    t_start = cumulative[idx * LINES_PER]
    t_end   = cumulative[idx * LINES_PER + len(chunk)]   # ← 修正点
    t_len   = t_end - t_start

    audio_part = TEMP / f"audio_{idx}.mp3"
    mp4_part   = TEMP / f"part_{idx:02d}.mp4"

    # ffmpeg -ss -t で音声を切り出し
    subprocess.run([
        "ffmpeg", "-y",
        "-ss", f"{t_start}", "-t", f"{t_len}",
        "-i", str(FULL_MP3),
        "-acodec", "copy", str(audio_part)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    print(f"▶️ part {idx+1}/{len(parts)}  行数={len(chunk)}  "
          f"start={t_start:.1f}s len={t_len:.1f}s")

    extra = {}
    if args.fsize_top: extra["fsize_top"] = args.fsize_top
    if args.fsize_bot: extra["fsize_bot"] = args.fsize_bot

    build_video(chunk, BG_PNG, audio_part, mp4_part,
                rows=ROWS, **extra)
    part_files.append(mp4_part)

# ──────────── concat ───────────────────
concat_txt = TEMP / "concat.txt"
concat_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in part_files))

subprocess.run([
    "ffmpeg", "-y",
    "-f", "concat", "-safe", "0",
    "-i", str(concat_txt),
    "-c", "copy", str(FINAL_MP4)
], check=True)

print("✅ 完成:", FINAL_MP4)

# 後始末（不要ならコメントアウトしておく）
# shutil.rmtree(TEMP)

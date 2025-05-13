#!/usr/bin/env python3
"""
長尺台本 (lines.json) → 40 行ごとに分割レンダリング → ffmpeg で結合
python chunk_builder.py path/to/lines.json bg.png final_output.mp4
"""
import json, math, subprocess, sys
from pathlib import Path

from subtitle_video import build_video  # 既存関数を再利用

# ---------------- 受け取り ----------------
script_json, bg_png, final_mp4 = map(Path, sys.argv[1:4])
MAX_LINES = 40                      # 1 チャンク 40 行 ≒ 1.5〜2 分

TEMP = Path("temp")
TEMP.mkdir(exist_ok=True)

lines = json.loads(script_json.read_text())       # [[spk,line1,line2,dur]...]

# ---------------- チャンクごとに動画作成 ---------------
parts = [lines[i:i+MAX_LINES] for i in range(0, len(lines), MAX_LINES)]
part_files = []

for idx, chunk in enumerate(parts):
    audio = TEMP / f"audio_{idx}.mp3"             # 既存フローで生成済み想定
    mp4   = TEMP / f"part_{idx:02d}.mp4"

    print(f"▶️ part {idx+1}/{len(parts)}  行数={len(chunk)}")
    build_video(chunk, bg_png, audio, mp4,
                rows=2,)
    part_files.append(mp4)

# ---------------- ffmpeg concat ----------------------
concat_txt = TEMP / "concat.txt"
concat_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in part_files))

subprocess.run([
    "ffmpeg","-y","-f","concat","-safe","0",
    "-i", str(concat_txt), "-c","copy", str(final_mp4)
], check=True)

print("✅ 完成:", final_mp4)

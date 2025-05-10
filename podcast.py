from pathlib import Path
from pydub import AudioSegment

def concat_mp3(parts:list[Path],out:Path):
    merged=AudioSegment.empty()
    for p in parts:
        merged+=AudioSegment.from_file(p)
    merged.export(out,format="mp3")

"""CPU-only audio validation/preview, run in the existing audio-capable Python."""
import json
import sys
from pathlib import Path
import numpy as np
import soundfile as sf


def main():
    with sf.SoundFile(sys.argv[1]) as source:
        if source.format not in {"WAV", "WAVEX", "FLAC", "OGG", "MP3"}:
            raise ValueError("対応していない音声形式です")
        expected = {".wav": {"WAV", "WAVEX"}, ".flac": {"FLAC"}, ".ogg": {"OGG"}, ".mp3": {"MP3"}}
        if source.format not in expected.get(Path(sys.argv[1]).suffix.lower(), set()):
            raise ValueError("拡張子と音声ファイルの内容が一致しません")
        if not 1 <= source.channels <= 2 or not 8000 <= source.samplerate <= 96000:
            raise ValueError("音源は1〜2ch、8〜96 kHzにしてください")
        seconds = source.frames / source.samplerate
        if not 0.1 <= seconds <= 1200:
            raise ValueError("音源は0.1秒〜20分にしてください（切り捨てはしません）")
        frames = 0
        with sf.SoundFile(sys.argv[2], mode="w", samplerate=source.samplerate,
                          channels=source.channels, subtype="PCM_16", format="WAV") as preview:
            for block in source.blocks(blocksize=65536, dtype="float32", always_2d=True):
                if not np.isfinite(block).all():
                    raise ValueError("音声に非有限値があります")
                frames += len(block)
                preview.write(block)
        if frames != source.frames:
            raise ValueError("音声が途中で破損しています")
        print(json.dumps({"duration": seconds, "frames": frames, "sample_rate": source.samplerate,
                          "channels": source.channels, "format": source.format}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)

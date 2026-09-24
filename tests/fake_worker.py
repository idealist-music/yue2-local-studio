"""Explicit test-only engine. Its two-second sine wave is NOT a YuE2 song."""
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio.storage import write_json


def emit(kind, job_id=None, **data):
    print(json.dumps({"type": kind, "job_id": job_id, **data}), flush=True)


def main():
    json.loads(sys.stdin.readline())
    emit("ready", pid=os.getpid(), pipeline_loads=1, engine="test")
    for line in sys.stdin:
        message = json.loads(line)
        if message["type"] == "shutdown":
            return
        job_id, req = message["job_id"], message["request"]
        print(f"TEST START {job_id} pid={os.getpid()}", file=sys.stderr, flush=True)
        emit("started", job_id)
        if req["style"] == "__TEST_CRASH__":
            os._exit(7)
        if req["style"] == "__TEST_OOM__":
            emit("error", job_id, code="cuda_oom", summary="テスト用OOM（実際のGPUは未使用）")
            return
        if req["style"] == "__TEST_SAVE_FAILURE__":
            emit("error", job_id, code="save_failed", summary="テスト用保存エラー")
            return
        time.sleep(1.2 if req["style"] == "__TEST_SLOW__" else 0.15)
        output = Path(message["output"])
        output.mkdir(parents=True, exist_ok=False)
        with wave.open(str(output / "preview.wav"), "wb") as wav:
            wav.setparams((1, 2, 8000, 16000, "NONE", "not compressed"))
            wav.writeframes(b"".join(struct.pack("<h", int(800 * math.sin(2 * math.pi * 220 * n / 8000))) for n in range(16000)))
        write_json(output / "request.json", req)
        write_json(output / "config.json", {"engine": "test", "pid": os.getpid(), "pipeline_loads": 1})
        if req["cot"] != "off":
            (output / "score.abc").write_bytes(req.get("abc", 'X:1\nM:4/4\nL:1/4\nK:C\n"C"C D E F|\n').encode("utf-8"))
        flags = {"abc": False, "semantic": req["style"] == "__TEST_TRUNCATED__"}
        files = {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in output.iterdir()}
        write_json(output / "result.json", {"status": "complete", "audio_seconds": 2.0, "truncated": flags, "artifacts": files, "engine": "test"})
        print(f"TEST END {job_id} pid={os.getpid()}", file=sys.stderr, flush=True)
        if req["style"] == "__TEST_CRASH_AFTER_SAVE__":
            os._exit(8)
        emit("completed", job_id, duration=2, truncated=flags, pid=os.getpid())


if __name__ == "__main__":
    main()

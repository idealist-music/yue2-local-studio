#!/usr/bin/env python3
"""Persistent YuE2 worker. Only the existing YuE environment imports model packages."""
from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import signal
import sys
import threading
import traceback

# Reserve the original stdout descriptor for JSON, including when native code prints.
PROTOCOL = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
sys.stdout = sys.stderr

from studio.storage import write_json

CANCELLED = threading.Event()
ACTIVE = False


class SamplingLimitError(ValueError):
    def __init__(self, phase, detail, summary):
        super().__init__(detail)
        self.phase = phase
        self.summary = summary


def validate_sampling_limit(value, phase, minimum, *, prefix_tokens=None, context=None):
    """Validate a user override against the loaded pipeline's real limits."""
    if value is None:
        return
    if type(value) is not int or value <= 0:
        raise SamplingLimitError(phase, f"{phase}_max_tokens must be a positive integer",
                                 "最大トークン数には正の整数を指定してください。")
    if value < minimum:
        raise SamplingLimitError(
            phase, f"{phase}_max_tokens={value} is below loaded YuE2 min_tokens={minimum}",
            "入力した最大トークン数が、ロード済みYuE2の対象段階のmin_tokens未満です。値を確認してください。")
    if prefix_tokens is not None and context is not None and prefix_tokens + value > context:
        raise SamplingLimitError(
            "context", f"{phase}_max_tokens={value} + prefix_tokens={prefix_tokens} exceeds context={context}",
            "歌詞・譜面を含む入力prefixと最大トークン数の合計がYuE2のコンテキスト上限を超えています。値を小さくしてください。自動調整はしていません。")


def sampling_overrides(message, pipe):
    """Build only explicitly requested YuE sampling overrides."""
    request = message["request"]
    generation = pipe.generation_config
    context = int(generation.context)
    try:
        model_config = json.loads((Path(pipe.model_dir) / "config.json").read_text(encoding="utf-8"))
        model_context = model_config.get("max_position_embeddings")
        if type(model_context) is int and model_context > 0:
            context = min(context, model_context)
    except (OSError, ValueError, TypeError):
        pass

    values = {
        "abc": request.get("abc_max_tokens"),
        "semantic": request.get("semantic_max_tokens"),
    }
    result = {}
    for phase, value in values.items():
        if value is None:
            continue
        defaults = getattr(generation, phase)
        prefix_tokens = None
        if phase == "abc" and request.get("cot") != "off" and request.get("abc") is None:
            # Exact prompt tokenization is available before planning. YuE's own
            # sampler repeats this check immediately before model prefill.
            from yue2.protocol import SongRequest, token_prefixes
            prompt = SongRequest(**{k: v for k, v in request.items()
                                    if k not in ("abc_max_tokens", "semantic_max_tokens")})
            prefix_tokens = len(token_prefixes(prompt, pipe.tokenizer))
        validate_sampling_limit(value, phase, defaults.min_tokens,
                                prefix_tokens=prefix_tokens, context=context)
        result[f"{phase}_sampling"] = {"max_tokens": value}
    return result


def emit(kind, job_id=None, **data):
    PROTOCOL.write(json.dumps({"type": kind, "job_id": job_id, **data}, ensure_ascii=False, allow_nan=False) + "\n")
    PROTOCOL.flush()


def stop(signum, frame):
    CANCELLED.set()
    if not ACTIVE:
        raise SystemExit(0)


def classify(exc, saving=False, loading=False):
    message = str(exc)
    if isinstance(exc, SamplingLimitError):
        return "sampling_limit", exc.summary
    if "requested generation budget exceeds" in message or "prefix" in message.lower() and "context" in message.lower():
        return "sampling_limit", "歌詞・譜面を含む入力prefixと最大トークン数の合計がYuE2のコンテキスト上限を超えています。値を小さくしてください。自動調整はしていません。"
    if "out of memory" in message.lower() or type(exc).__name__ == "OutOfMemoryError":
        return "cuda_oom", "GPUメモリが不足しました。設定は変更していません。空きVRAMを確認してください"
    if saving:
        return "save_failed", "成果物を保存できませんでした。空き容量・書き込み権限と詳細ログを確認してください"
    if isinstance(exc, FileNotFoundError) or type(exc).__name__ == "LocalEntryNotFoundError":
        return "model_missing", "モデル・VAEが見つかりません。既存キャッシュまたは設定のパスを確認してください。自動ダウンロードはしません"
    if isinstance(exc, InterruptedError):
        return "interrupted", "生成が中断されました"
    if loading:
        return "worker_load_failed", "YuE2を読み込めませんでした。設定と詳細ログを確認してください"
    return "generation_failed", "生成に失敗しました。詳細ログを確認してください"


def main():
    global ACTIVE
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    pipe = None
    initial = json.loads(sys.stdin.readline())
    runtime = initial["runtime"]
    try:
        from yue2 import YuE2Pipeline
        import soundfile as sf
        import torch
        kwargs = {**runtime["pipeline"], "device": runtime["device"], "local_files_only": True,
                  "revision": runtime.get("revision"), "vae_revision": runtime.get("vae_revision"),
                  "cache_dir": runtime.get("cache_dir"), "progress": True}
        pipe = YuE2Pipeline.from_pretrained(runtime["model"], vae=runtime["vae"], **kwargs)
        emit("ready", pid=os.getpid(), pipeline_loads=1, python=sys.version.split()[0],
             yue2=importlib.metadata.version("yue2-infer"), torch=torch.__version__,
             model=str(pipe.model_dir), vae=str(pipe.vae_dir), device=str(pipe.device))
        for line in sys.stdin:
            if CANCELLED.is_set():
                break
            message = json.loads(line)
            if message["type"] == "shutdown":
                break
            job_id, output = message["job_id"], Path(message["output"])
            ACTIVE, saving = True, False
            emit("started", job_id)
            try:
                output.mkdir(parents=True, exist_ok=False)
                if message["type"] == "plan":
                    plan = pipe.plan(style=message["style"], lyrics=message["lyrics"],
                                     cot="full", seed=int(message["seed"]), id=job_id,
                                     cancelled=CANCELLED.is_set)
                    if getattr(plan, "truncated", False):
                        raise RuntimeError("plan_truncated")
                    saving = True
                    plan.save(output)
                    score = output / "score.abc"
                    if not score.is_file() or not score.read_text(encoding="utf-8").strip():
                        raise RuntimeError("plan_invalid")
                    write_json(output.parent / "plan-receipt.json", {"pid": os.getpid(), "pipeline_loads": 1,
                                                                       "request": {"style": message["style"], "lyrics": message["lyrics"], "cot": "full", "seed": int(message["seed"])}})
                    emit("plan_completed", job_id, truncated=False)
                    del plan
                    continue
                # Remove app-only settings before building SongRequest and pass
                # only explicitly supplied stage overrides to the YuE pipeline.
                request = dict(message["request"])
                sampling_kwargs = sampling_overrides(message, pipe)
                request.pop("abc_max_tokens", None)
                request.pop("semantic_max_tokens", None)
                song = pipe(**request, **sampling_kwargs, cancelled=CANCELLED.is_set)
                saving = True
                song.save_artifacts(output)
                # Read the actual saved audio, never an estimated/requested duration.
                info = sf.info(output / "audio.flac")
                receipt = {"duration": info.frames / info.samplerate, "truncated": song.truncated,
                           "pid": os.getpid(), "pipeline_loads": 1}
                write_json(output.parent / "worker-receipt.json", receipt)
                emit("completed", job_id, **receipt)
                del song
            except Exception as exc:
                traceback.print_exc(file=sys.stderr)
                code, summary = classify(exc, saving=saving)
                emit("error", job_id, code=code, summary=summary)
                # Exit after errors; a user-directed restart gets a clean pipeline.
                return 2
            finally:
                ACTIVE = False
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        code, summary = classify(exc, loading=True)
        emit("error", code=code, summary=summary)
        return 2
    finally:
        if pipe is not None:
            pipe.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

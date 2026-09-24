from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPELINE_DEFAULTS = {
    "memory_budget_gib": 24.0,
    "backend": "torch",
    "quantization": "none",
    "offload_ar": False,
    "vae_core_frames": 1024,
    "verify_hashes": True,
}


@dataclass(frozen=True)
class Config:
    python: str
    model: str
    vae: str
    device: str
    pipeline: dict
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 7860
    revision: str | None = None
    vae_revision: str | None = None
    cache_dir: str | None = None
    allowed_hosts: tuple = ("127.0.0.1", "localhost", "[::1]")
    engine: str = "yue2"
    sheetsage_python: str | None = None
    sheetsage_model: str | None = None
    abc_tools: str | None = None

    def runtime(self):
        return {"python": self.python, "model": self.model, "vae": self.vae,
                "device": self.device, "pipeline": self.pipeline,
                "revision": self.revision, "vae_revision": self.vae_revision,
                "cache_dir": self.cache_dir, "local_files_only": True,
                "engine": self.engine}


def load_config(path=ROOT / "config.local.json", *, test_engine=False):
    path = Path(path).resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    allowed = {"python", "model", "vae", "device", "pipeline", "data_dir", "host", "port",
               "revision", "vae_revision", "cache_dir", "allowed_hosts",
               "sheetsage_python", "sheetsage_model", "abc_tools"}
    if set(raw) - allowed:
        raise ValueError(f"未対応の設定: {', '.join(sorted(set(raw) - allowed))}")
    for name in ("python", "model", "vae", "device"):
        if not isinstance(raw.get(name), str) or not raw[name]:
            raise ValueError(f"{name} を指定してください")
    if not Path(raw["python"]).is_absolute():
        raise ValueError("python は絶対パスを指定してください")
    for key in ("sheetsage_python", "sheetsage_model", "abc_tools"):
        if raw.get(key) is not None and (not isinstance(raw[key], str) or not Path(raw[key]).is_absolute()):
            raise ValueError(f"{key} は絶対パスを指定してください")
    # Compare environment directories, not resolved Python symlinks (venvs share a binary).
    if raw.get("sheetsage_python") and Path(raw["sheetsage_python"]).parent.parent.resolve() == Path(raw["python"]).parent.parent.resolve():
        raise ValueError("SheetSage2 には YuE2 と別のPython環境を指定してください")
    pipeline = {**PIPELINE_DEFAULTS, **raw.get("pipeline", {})}
    if set(pipeline) - set(PIPELINE_DEFAULTS):
        raise ValueError("pipeline にローカル実装で未確認の設定があります")
    if pipeline["backend"] not in ("torch", "torch-eager"):
        raise ValueError("このアプリの backend は torch / torch-eager のみ対応します")
    if pipeline["quantization"] not in ("none", "fp8"):
        raise ValueError("quantization は none / fp8 を指定してください")
    for key in ("offload_ar", "verify_hashes"):
        if type(pipeline[key]) is not bool:
            raise ValueError(f"{key} は boolean です")
    budget = pipeline["memory_budget_gib"]
    if type(budget) not in (int, float) or not math.isfinite(budget) or budget <= 2:
        raise ValueError("memory_budget_gib は 2 より大きい有限数です")
    frames = pipeline["vae_core_frames"]
    if type(frames) is not int or frames < 1:
        raise ValueError("vae_core_frames は正の整数です")
    port = raw.get("port", 7860)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("port は 1〜65535 です")
    data_dir = Path(raw.get("data_dir", "data")).expanduser()
    if not data_dir.is_absolute():
        data_dir = path.parent / data_dir
    for name in ("model", "vae", "cache_dir"):
        value = raw.get(name)
        if value and (value.startswith(".") or value.startswith("~")):
            p = Path(value).expanduser()
            raw[name] = str((path.parent / p).resolve())
    hosts = raw.get("allowed_hosts", ["127.0.0.1", "localhost", "[::1]"])
    if not isinstance(hosts, list) or not hosts or any(not isinstance(h, str) or "*" in h for h in hosts):
        raise ValueError("allowed_hosts はワイルドカードを含まないホスト名の配列です")
    return Config(**{k: v for k, v in raw.items() if k not in ("pipeline", "data_dir", "allowed_hosts")},
                  pipeline=pipeline, data_dir=data_dir.resolve(), allowed_hosts=tuple(hosts),
                  engine="test" if test_engine else "yue2")

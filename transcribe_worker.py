"""One transcription per separate SheetSage2 process. Exiting releases its GPU."""
import inspect
import json
import os
from pathlib import Path
import sys
import traceback

# Native libraries may print to fd 1: keep the protocol on a duplicate descriptor.
PROTOCOL = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1, encoding="utf-8")
os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
sys.stdout = sys.stderr


def emit(**data):
    PROTOCOL.write(json.dumps(data, ensure_ascii=False) + "\n")
    PROTOCOL.flush()


def import_local_sheetsage(model_path: Path):
    """Load the checked-out SheetSage2 class, bypassing Transformers auto dispatch.

    The standalone model directory contains weights/configuration, while the
    sibling ``SheetSage2`` directory contains the Python package and its
    relative imports.  Keeping the package on sys.path avoids the Hugging Face
    dynamic-module cache entirely.
    """
    candidates = []
    if model_path.name == "SheetSage2":
        candidates.append(model_path)
    candidates.extend((model_path.parent / "SheetSage2", Path(__file__).resolve().parent / "models" / "SheetSage2"))
    package = next((path for path in candidates if (path / "__init__.py").is_file()), None)
    if package is None:
        raise ValueError(
            "ローカルSheetSage2 Pythonパッケージが見つかりません。"
            "モデルディレクトリの隣にSheetSage2/modeling_sheetsage2.pyを配置してください"
        )
    parent = str(package.parent.resolve())
    if parent not in sys.path:
        sys.path.insert(0, parent)
    # Deliberately use the local package import requested by the standalone
    # setup; this never asks Transformers to resolve a dynamic module.
    from SheetSage2.modeling_sheetsage2 import SheetSage2Model
    return SheetSage2Model


def main():
    request = json.loads(sys.stdin.readline())
    job_id = request["job_id"]
    model = None
    try:
        import torch
        settings = request["settings"]
        standalone_model_path = Path(settings["model"])
        if not standalone_model_path.is_dir():
            raise ValueError("SheetSage2は取得済みのローカルモデルディレクトリを指定してください")
        SheetSage2Model = import_local_sheetsage(standalone_model_path)
        model = SheetSage2Model.from_pretrained(
            standalone_model_path,
            local_files_only=True,
        ).eval().to(settings["device"])
        if "melody_only" not in inspect.signature(model.transcribe).parameters:
            raise ValueError("このSheetSage2には公式melody_only APIがありません。対応版を専用環境に準備してください")
        result = model.transcribe(request["audio"], output_dir=request["output"], melody_only=True)
        warnings = result.get("warnings", [])
        if result.get("abc_error") or not isinstance(result.get("abc"), str) or not result["abc"].strip():
            raise ValueError(f"採譜から利用できるABCが得られません: {result.get('abc_error')}; warnings={warnings}")
        output = Path(request["output"])
        (output / "score.abc").write_bytes(result["abc"].encode("utf-8"))
        receipt = {"warnings": warnings, "settings": settings, "melody_only": True,
                   "torch": torch.__version__, "model_class": type(model).__module__,
                   "model_config": model.config.to_dict()}
        (output / "studio-transcription.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        emit(type="completed", job_id=job_id, warnings=warnings)
        return 0
    except Exception as exc:
        traceback.print_exc()
        partial = getattr(exc, "result", None)
        if isinstance(partial, dict):
            print("Transcription warnings:", partial.get("warnings"), file=sys.stderr)
        emit(type="error", job_id=job_id, code="transcription_failed", summary=str(exc)[:3000])
        return 2
    finally:
        if model is not None:
            del model
        # A clean process exit, checked by the queue, is the GPU release boundary.


if __name__ == "__main__":
    raise SystemExit(main())

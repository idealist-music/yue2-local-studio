"""Merge reviewed, local SheetSage2 and MERT snapshots for the offline worker."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    for name in ("source", "mert", "destination"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    source, mert, destination = (getattr(args, name).expanduser().resolve() for name in
                                 ("source", "mert", "destination"))
    if destination.exists():
        raise SystemExit("Destination already exists; it was not changed")
    if source.name != "SheetSage2" or not (source / "modeling_sheetsage2.py").is_file():
        raise SystemExit("The local SheetSage2 package must be named SheetSage2")
    if not (mert / "model.safetensors").is_file():
        raise SystemExit("The local MERT-v2-FullSong weights are missing")
    config = json.loads((source / "config.json").read_text(encoding="utf-8"))
    if config.get("weights_format") != "adapter" or config.get("base_model_name_or_path") != "m-a-p/MERT-v2-FullSong":
        raise SystemExit("Expected the official SheetSage2 adapter and MERT-v2-FullSong parent")
    sys.path.insert(0, str(source.parent))
    from SheetSage2.modeling_sheetsage2 import SheetSage2Model

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sheetsage-build-", dir=destination.parent) as temp:
        model = SheetSage2Model.from_pretrained(source, base_model_path=mert, local_files_only=True).eval()
        model.save_pretrained(temp)
        del model
        result = Path(temp)
        merged = json.loads((result / "config.json").read_text(encoding="utf-8"))
        if merged.get("weights_format") != "merged" or not (result / "model.safetensors").is_file():
            raise RuntimeError("The standalone snapshot is incomplete")
        if destination.exists():
            raise RuntimeError("Destination appeared during the build; it was not overwritten")
        os.rename(result, destination)
    print(f"Standalone snapshot ready: {destination}")


if __name__ == "__main__":
    main()

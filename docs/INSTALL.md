# Install on Linux or WSL2 Ubuntu

[日本語](INSTALL.ja.md) · [External versions and terms](EXTERNAL_DEPENDENCIES.md)

Run `./setup.sh` for an interactive choice: app only, normal YuE2 generation, or Cover/Motif transcription. Each clone, package installation, model download, and standalone-model build displays its source, destination, approximate size, and action before asking for confirmation. `./setup.sh --doctor` is read-only and reports `OK`, `MISSING`, or `MANUAL` for each stage. The installer never invokes `sudo` or `apt` and never overwrites `config.local.json`, a model, or an existing complete venv. Stop and rerun the same stage after fixing an interrupted download. Keep the external directory outside this repository.

```bash
./setup.sh --stage app
./setup.sh --stage yue --external-dir /absolute/path/to/yue2-external
./setup.sh --stage cover --external-dir /absolute/path/to/yue2-external
./setup.sh --doctor
```

`--stage yue` includes the app stage; `--stage cover` includes app and YuE2. Omit `--stage` for the menu. Use `--yue-dir /absolute/path/to/YuE` to reuse an existing official checkout. A configured YuE Python path is also detected. Existing packages and files are inspected; version mismatches or incomplete directories require manual review. The installer only runs `git clone` for a missing YuE checkout; it performs no Git update or checkout of existing trees.

## 1. App and normal generation

The app uses its own `.venv` and `requirements.txt`. Install Python 3.10 or later with `venv` and `pip` first. On Ubuntu, an administrator can install `python3`, `python3-venv`, `python3-pip`, and `git` using the distribution package manager. The installer itself makes no system changes.

For YuE2, the installer clones the [official YuE repository](https://github.com/multimodal-art-projection/YuE) at the `yue2-v0.1.6` release tag into the external directory, creates a dedicated venv, and runs the official `python -m pip install .` from that checkout. The [YuE generation guide](https://github.com/multimodal-art-projection/YuE/blob/main/docs/generation.md) uses Python 3.12; its package metadata accepts Python 3.10+. The installer prefers `python3.12` if available and otherwise uses `python3`; the recorded working environment used Python 3.10, `yue2-infer` 0.1.6, PyTorch 2.10.0 with a CUDA 12.8 wheel, and Transformers 4.57.6. Check the installed PyTorch build against the [official PyTorch selector](https://pytorch.org/get-started/locally/) and your driver; `pip install .` alone does not prove CUDA works.

The supported YuE2 starting point is Linux, a BF16-capable NVIDIA GPU with 24 GB VRAM, approximately 24 GB available host RAM, and one generation at a time. Lower-memory settings may work but are not established by this installer. Verify the driver with `nvidia-smi` (inside Ubuntu for WSL2), and inspect the YuE venv with `.../venv/bin/python -c 'import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.is_bf16_supported())'`. WSL2 also needs a compatible Windows NVIDIA driver and GPU passthrough. The installer does not install drivers or a system CUDA toolkit.

Normal generation needs the [YuE2-3B](https://huggingface.co/m-a-p/YuE2-3B) and [YuE2-Vae](https://huggingface.co/m-a-p/YuE2-Vae) snapshots because the app worker loads them offline. The installer offers downloads pinned to the revisions in `config.example.json` into the external directory (roughly 8–10 GiB and 0.6 GiB, plus cache and Python packages). It then suggests local `model`, `vae`, `python`, and `abc_tools` paths. The required helper is `YuE/skills/yue2-music/scripts/abc_tools.py`; it is checked without copying it into the app.
An existing Hugging Face cache is reused only when it contains the configured exact revision and complete weights; the app can retain the corresponding model ID in that case.

## 2. Cover and Motif audio transcription

Run `./setup.sh --stage cover` only if you need audio transcription. ABC-only Cover still needs YuE2 and its ABC helper, but not SheetSage2. The installer creates a separate Python 3.10/3.11 venv for [SheetSage2](https://huggingface.co/m-a-p/SheetSage2), downloads its reviewed revision `488abe28ef4db3dbb056da19cb49d80f4b14bc61` (about 0.25 GiB), and downloads its specified [MERT-v2-FullSong](https://huggingface.co/m-a-p/MERT-v2-FullSong) parent at `d8ba1c745e733b3908ce6ad16ebeb17ac7600a42` (about 2.6 GiB). It follows the [official SheetSage2 requirements](https://huggingface.co/m-a-p/SheetSage2/blob/main/README.md): PyTorch/TorchAudio 2.8.0 from the CUDA 12.6 wheel index and the snapshot's pinned `requirements.txt`. If the venv's seeded `setuptools` differs from the pinned version, the installer shows the change and asks before reconciling it. The merged standalone snapshot needs roughly another 3 GiB of disk space and substantial free RAM during creation.

If Hugging Face reports denied access, visit both model pages, accept any required terms, and run `<sheetsage-venv>/bin/hf auth login` interactively. Then rerun the stage. Do not put a token in shell commands, logs, this repository, or `config.local.json`. You must assess the terms for each exact artifact and obtain any necessary permission for your use; the recorded revisions document runtime compatibility, not license clearance.

This app's worker directly imports `SheetSage2.modeling_sheetsage2.SheetSage2Model`, calls `from_pretrained(standalone_path, local_files_only=True)`, and requires `transcribe(..., melody_only=True)`. The installer keeps the official source at `<external>/SheetSage2/`, saves the merged offline model beside it at `<external>/SheetSage2-standalone/`, verifies the direct class import and `melody_only` parameter, and proposes `sheetsage_python` and `sheetsage_model`. A successful generic `AutoModel` example is not used as the app's readiness check. Model files remain outside the published app tree.

## 3. FFmpeg and system checks

The official SheetSage2 audio instructions specify FFmpeg 6.1 with its shared libraries. The current Motif clip code calls **`/usr/bin/ffmpeg`** specifically; an FFmpeg executable elsewhere on `PATH` does not satisfy that Motif step. The doctor checks that path, its version, and `ldd` results. Cover audio transcription depends on the SheetSage2 audio stack and may fail without its FFmpeg requirement; ABC-only Cover does not call FFmpeg. Check manually:

```bash
command -v ffmpeg
/usr/bin/ffmpeg -version
ldd /usr/bin/ffmpeg | grep 'not found'
command -v ffprobe && ffprobe -version
```

An Ubuntu/WSL2 administrator may use `sudo apt update` and `sudo apt install ffmpeg`, then verify the actual version. Ubuntu releases may provide a version other than 6.1. If so, arrange a trusted FFmpeg 6.1 build and matching shared libraries at `/usr/bin/ffmpeg` through the administrator; do not assume a Windows `ffmpeg.exe` or a binary elsewhere on `PATH` will work for Motif. Consult [FFmpeg's download and license information](https://ffmpeg.org/download.html).

## Finish and optional model load checks

If `config.local.json` already exists, the installer prints suggested paths and leaves every existing value untouched. If it is missing, it offers to create one from `config.example.json` with detected paths. Confirm `model`, `vae`, `revision`, `vae_revision`, `device`, `python`, `abc_tools`, `sheetsage_python`, and `sheetsage_model` as needed. Keep this private file and downloaded models out of Git.

```bash
./setup.sh --doctor
./setup.sh --load-check yue    # Loads the app's YuE worker; no generation
./setup.sh --load-check sheet  # Loads the exact offline SheetSage2 class on CPU; no transcription
./run.sh
```

Load checks are optional, explicit, and can take minutes and much memory. The SheetSage2 CPU load confirms the package and standalone weights but does not prove GPU transcription or musical accuracy. Diagnostics report file/package readiness separately from these load checks. The app is on port 7860 by default. See [README.md](../README.md) for use and network settings, [README-COVERS.md](README-COVERS.md) for the Cover workflow, and [EXTERNAL_DEPENDENCIES.md](EXTERNAL_DEPENDENCIES.md) for versions and terms links.

# YuE2 Local Studio

YuE2 Local Studio is a local web interface for submitting YuE2 music-generation jobs and managing their results. It also includes ABC-based cover workflows, phrase-based motif workflows, and ABC/MIDI round-trip editing. The web application runs in its own lightweight Python environment; YuE2 and SheetSage2 run in separate environments.

The application source does not include model weights, YuE2, SheetSage2, MERT, VAE files, FFmpeg, or the official YuE ABC helper. Obtain these separately from their official sources and configure their local paths. The recorded versions, revisions, and terms-check links are in [External Dependencies](EXTERNAL_DEPENDENCIES.md). No model download is performed automatically by the application.

## Requirements

- Linux is the documented target; the source was developed and checked on WSL2/Ubuntu. Other platforms have not been verified.
- Python 3.10 is the version observed in the development environment. The app environment installs only the packages in `requirements.txt`.
- YuE2 needs its own supported Python environment, PyTorch/CUDA setup, model weights, and VAE. Follow the current YuE2 setup documentation for its hardware requirements. GPU generation requires a compatible GPU and enough VRAM for the selected model and settings. CPU mode is useful for limited checks, but this project does not claim that CPU music generation is practical.
- SheetSage2 transcription needs a separate Python environment, its model package and weights, MERT-v2-FullSong files, and a compatible GPU setup.
- Motif audio clipping currently invokes `/usr/bin/ffmpeg` directly. Install FFmpeg 6.1 with its shared libraries at that path for the documented motif workflow.

The application has no account system or authentication. Keep it on localhost or a trusted private network. Do not expose it directly to the internet. LAN access requires deliberately configuring the listen host and allowed host names in `config.local.json`.

## Setup

From this directory, create the app-only virtual environment and install the dependencies declared for the app:

```bash
./setup.sh
```

Copy `config.example.json` to `config.local.json`. Update the required absolute path for `python` to the Python executable in your YuE2 environment. Set `model`, `vae`, `device`, and the pinned revisions to values available to that environment. The example revisions are copied from the development configuration; verify that they remain available and permitted before use. Set `abc_tools` to the official YuE `skills/yue2-music/scripts/abc_tools.py` file, or leave it `null` if the helper is in the location derived from the configured YuE Python environment. `sheetsage_python` and `sheetsage_model` can remain `null` until SheetSage2 is installed. Any explicit paths in these fields must be absolute. The app reads `config.local.json`; it does not load `.env` files.

For ABC-based generation, the official YuE ABC helper must be available from a separate YuE installation. Audio transcription and motif workflows additionally need the separately installed SheetSage2 package, weights, MERT files, FFmpeg, and dedicated environment described in [README-COVERS.md](README-COVERS.md). These external components are not included here. Check their exact artifact terms and required access with their providers; users are responsible for obtaining permissions applicable to their intended use. Record the model revisions you install in your local configuration and consult [External Dependencies](EXTERNAL_DEPENDENCIES.md).

Start the app with:

```bash
./run.sh
```

It listens on port 7860. With the default configuration, open <http://127.0.0.1:7860>. Stop it with Ctrl+C. The app writes its database, logs, uploads, and generated artifacts under `data/` (or the configured `data_dir`). Keep backups of that directory if you need to preserve your work.

To bind to a LAN interface, set `host` and `allowed_hosts` explicitly in your private `config.local.json`. There is no authentication; use only a network you trust and do not forward the port to the public internet.

## Features and limitations

- YuE2 generation with job history and saved results.
- Cover generation from compatible YuE2 native ABC or locally transcribed audio. Transcription output requires review before generation; automatic lyric recognition and lyric writing are not provided. See [README-COVERS.md](README-COVERS.md).
- Motif composition from a transcribed audio section. See [README-MOTIF.md](README-MOTIF.md).
- ABC and MIDI editing workflows. See [README-MIDI-ROUNDTRIP.md](README-MIDI-ROUNDTRIP.md).

ABC conversion supports the formats accepted by the official YuE helper; it does not promise compatibility with arbitrary ABC notation. MIDI round trips can discard performance data that ABC cannot represent. Listen to generated results and review imported notation.

## Development checks

Install the optional app-side development requirements into the app environment with `python -m pip install -r requirements-dev.txt`. The included tests cover the local app and MIDI code. Tests that need YuE, SheetSage2, browser installations, or real external audio are not part of this release test set. This release tree has not been tested in a clean environment.

## Data and privacy

Databases, logs, uploaded audio, lyrics, and generated outputs are runtime data and are not part of this source tree. Do not attach private audio, lyrics, configuration files, logs, or database files to public bug reports. Inspect and remove sensitive details before sharing diagnostics.

## Licensing

The original application code in `studio/`, `static/`, the app-specific root scripts and configuration template (`worker.py`, `transcribe_worker.py`, `audio_probe.py`, `run.sh`, `setup.sh`, and `config.example.json`), and `tests/` is licensed under the BSD Zero Clause License (0BSD); see [LICENSE](LICENSE). This grant applies only to that application-authored code. It does not relicense external libraries, YuE/YuE2 source, model code or weights, or separately installed software. [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) lists third-party material included in the release tree; [External Dependencies](EXTERNAL_DEPENDENCIES.md) lists separately installed components and official terms-check sources.

YuE inference code, YuE2/VAE, SheetSage2, MERT, and other model files have separate terms from their providers. The app publisher does not warrant that external terms permit a user's particular purpose or that any required permission has been obtained. Users must review the exact artifact terms and obtain necessary permissions. Do not infer commercial model rights from the app's 0BSD license. The app license does not assign rights to user inputs or generated music: generated audio is not automatically 0BSD or public domain. Check model terms, input rights, and applicable law separately.

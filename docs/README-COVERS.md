# Cover generation

Cover jobs use the normal generation queue but create a new song. The source audio is used for transcription and comparison; YuE2 receives compatible ABC as its musical condition. Existing songs, audio, and notation are not overwritten.

## Workflow

1. Open a saved song's cover action, or upload WAV, FLAC, MP3, OGG, or a UTF-8 ABC file from the cover screen.
2. Reuse saved ABC when available. If the source is audio without ABC, request transcription. Transcription stops at an ABC review step; it never starts generation automatically.
3. Review transcription warnings and edit the ABC if needed. Confirm the exact ABC that will be used.
4. Enter the lyrics, style, and seed. Lyrics from external audio are supplied by the user; this app does not recognize or generate lyrics.
5. Confirm the review and submit the cover as a new job.

Audio uploads are limited to 100 MiB, 0.1 seconds to 20 minutes, one or two channels, and 8–96 kHz. ABC input is limited to 256 KiB. The app validates uploaded audio with the configured YuE Python environment and stores uploads and previews under the runtime data directory.

## ABC behavior

The app calls the official YuE helper `skills/yue2-music/scripts/abc_tools.py` in read-only mode. It supports the helper's YuE2-native two-voice ABC format. For `melody`, it removes supported chord symbols while preserving the Vocal and Ins parts; `full` passes edited ABC unchanged. Cover jobs do not support `off`. Unsupported ABC syntax is rejected for correction rather than guessed at. Notation checks do not guarantee that the generated audio will reproduce a melody, voice, or waveform exactly.

Configure `abc_tools` in `config.local.json` if the helper is not at the location derived from the YuE Python environment. The helper is not included in this tree; obtain it from the official YuE distribution and review its terms.

## SheetSage2 transcription setup

Audio transcription uses a separate SheetSage2 Python environment. The worker imports the local `SheetSage2.modeling_sheetsage2.SheetSage2Model` package directly and calls `from_pretrained(..., local_files_only=True)`. A Transformers `AutoModel.from_pretrained(...)` setup command alone does not satisfy this worker's package import requirement.

Use `./setup.sh --stage cover` and the staged [installation guide](INSTALL.md). The guide covers the separate venv, pinned official SheetSage2 and MERT downloads, interactive access handling, local standalone model creation, `sheetsage_python`/`sheetsage_model`, and the optional direct-class load check. The worker needs the local `SheetSage2/` source beside the standalone model and `melody_only` support. The UI's configured state checks only files; it does not prove the weights load. Record actual revisions and review terms in [EXTERNAL_DEPENDENCIES.md](EXTERNAL_DEPENDENCIES.md).

## FFmpeg requirement for Motif

The Motif audio-clipping code currently invokes `/usr/bin/ffmpeg` directly. FFmpeg 6.1 and its shared libraries are documented in [INSTALL.md](INSTALL.md). Cover transcription does not use this fixed path but uses SheetSage2's audio stack. The FFmpeg path is fixed in the current release source.

## Saved data and privacy

Original audio, preview audio, ABC, transcription output, and job metadata are stored under the configured `data_dir`. This may include user audio and lyrics. Back up the runtime data directory privately; never add it to a source release or attach it to a public issue.

Model and helper terms are separate from the application license. Users must check the exact artifact terms and obtain any required permissions from the providers. The publisher does not guarantee that an external component is authorized for a user's purpose. Model files are not included in this tree; see [EXTERNAL_DEPENDENCIES.md](EXTERNAL_DEPENDENCIES.md).

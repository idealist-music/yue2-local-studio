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

Install SheetSage2 from its official distribution using that distribution's current instructions. Obtain and review the matching Python source package and model weights, MERT-v2-FullSong files, dependencies, access requirements, and license terms. Keep the SheetSage2 environment separate from YuE2 because their dependencies differ. This repository does not include SheetSage2 source, model weights, or MERT files and does not provide an unverified download or conversion command. The functionally checked SheetSage2 revision and official terms-check links are listed in [EXTERNAL_DEPENDENCIES.md](EXTERNAL_DEPENDENCIES.md); this does not certify license compliance.

The worker must be able to find the SheetSage2 Python package either inside the configured model directory (when that directory is named `SheetSage2`), beside the configured model directory as a `SheetSage2/` directory, or at this app's `models/SheetSage2/` path. The release tree intentionally does not create that model directory. Configure absolute paths in `config.local.json`:

```json
{
  "sheetsage_python": "/absolute/path/to/sheetsage-venv/bin/python",
  "sheetsage_model": "/absolute/path/to/local/sheetsage-model",
  "abc_tools": "/absolute/path/to/YuE/skills/yue2-music/scripts/abc_tools.py"
}
```

The model must be a local directory with a `config.json` and the files required by `SheetSage2Model.from_pretrained`. The worker runs offline. Keep a record of the source and model revisions used. The UI's configured status only checks for files; it does not prove the environment can load the model. The worker checks that the model's `transcribe` method supports `melody_only`.

## FFmpeg requirement for Motif

The Motif audio-clipping code currently invokes `/usr/bin/ffmpeg` directly. Install FFmpeg 6.1 and its shared libraries at that path for the documented Motif workflow. Cover transcription itself does not use this FFmpeg invocation. The FFmpeg path is fixed in the current release source.

## Saved data and privacy

Original audio, preview audio, ABC, transcription output, and job metadata are stored under the configured `data_dir`. This may include user audio and lyrics. Back up the runtime data directory privately; never add it to a source release or attach it to a public issue.

Model and helper terms are separate from the application license. Users must check the exact artifact terms and obtain any required permissions from the providers. The publisher does not guarantee that an external component is authorized for a user's purpose. Model files are not included in this tree; see [EXTERNAL_DEPENDENCIES.md](EXTERNAL_DEPENDENCIES.md).

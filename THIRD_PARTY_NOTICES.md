# Third-party notices

## Distributed contents

The release tree was reviewed for third-party source code, copied or modified
third-party code, bundled libraries, frontend bundles, fonts, images, audio,
models, and binaries. None were identified in the files being published.
The application frontend is served from its own source files; it does not
load a third-party JavaScript bundle, web font, or other frontend asset from a
CDN. The SVG mark is application-authored.

| Included, copied, or adapted third-party material | Use | Version/revision | Required notice/license | Source |
|---|---|---|---|---|
| None identified | — | — | No third-party material was identified that needs a reproduced license text or attribution in this release tree. This records the current inventory, not a review of users' separately installed artifacts. | — |

The app invokes YuE's `skills/yue2-music/scripts/abc_tools.py` from the
separately installed YuE distribution, and imports the separately installed
SheetSage2 Python package at runtime. Neither implementation is copied into
this release tree. Their distribution sources and terms are listed in
[EXTERNAL_DEPENDENCIES.md](EXTERNAL_DEPENDENCIES.md), not relicensed by this
application's license.

## Application license scope

The root [LICENSE](LICENSE) applies only to the application-authored source
and assets in this release: `studio/`, `static/`, `tests/`, `worker.py`,
`transcribe_worker.py`, `audio_probe.py`, `run.sh`, `setup.sh`, and
`config.example.json`. It does not change the terms for separately installed
software, models, user inputs, or generated audio. See the English and
Japanese READMEs and the external dependency guide for that distinction.

This inventory describes the current release tree only. If a future release
adds or vendors third-party code, assets, or binaries, identify their exact
versions and sources, preserve applicable copyright and license notices, and
include required license texts before distribution.

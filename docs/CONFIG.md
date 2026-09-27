# Local configuration (`config.local.json`)

`config.local.json` contains machine-specific paths and runtime settings for this installation. It is intentionally ignored by Git because it can reveal local paths and network configuration. Do not publish it. The tracked [`config.example.json`](../config.example.json) is a template, not a file the app reads automatically.

## Create and update the file

Run the setup stages you need and use the absolute paths printed under **Suggested config values**. The installer creates `config.local.json` only if it does not already exist. It does not merge new suggestions into an existing file. Add or update the matching keys manually, preserving settings you already have. You can start with the example when no local file exists:

```bash
cp config.example.json config.local.json
```

Then edit the YuE paths and any optional Cover/Motif paths. JSON does not allow comments or trailing commas. Unknown keys are rejected; do not add arbitrary options. Restart the app after editing the file.

Run `./setup.sh --doctor` to check paths and installed components without changing the environment. Optional worker load checks are documented in [INSTALL.md](INSTALL.md).

## Settings

All paths below are Linux/WSL paths. `python` must point to the YuE2 environment—not the app's `.venv`. YuE and SheetSage2 must use separate Python environments.

| Key | Required / default | Meaning |
| --- | --- | --- |
| `python` | Required; absolute path | Python executable in the YuE2 venv. |
| `model` | Required | YuE2 model repository ID or local model snapshot path. The worker loads files locally and does not download missing files at runtime; use an already available snapshot. |
| `vae` | Required | YuE2 VAE repository ID or local snapshot path, also available locally for offline loading. |
| `device` | Required | Device string passed to the YuE runtime, commonly `cuda:0`. GPU, driver, PyTorch build, and available memory must be compatible. |
| `revision` | Optional; example pins a revision | YuE2 model revision passed to the runtime. Keep it consistent with the local snapshot. |
| `vae_revision` | Optional; example pins a revision | VAE revision passed to the runtime. Keep it consistent with the local snapshot. |
| `abc_tools` | Optional; `null` in the example | Absolute path to the official YuE `abc_tools.py`. If omitted or `null`, the app derives it from the configured YuE Python environment. Set it explicitly if automatic discovery does not find the helper. |
| `sheetsage_python` | Optional; `null` | Absolute path to the Python executable in the separate SheetSage2 venv. Needed for audio transcription in Cover and Motif; not needed for normal generation or ABC-only Cover. |
| `sheetsage_model` | Optional; `null` | Absolute path to the local standalone SheetSage2 model used by the app's direct `SheetSage2Model` loader. Needed for audio transcription; it is not downloaded by the running app. |
| `pipeline` | Optional; defaults below | YuE pipeline runtime options. Use only keys and values supported by this app and the installed YuE version. |
| `pipeline.memory_budget_gib` | `24.0` | Memory budget value passed to the YuE pipeline; must be a finite number greater than 2. |
| `pipeline.backend` | `"torch"` | Backend passed to the pipeline. This app accepts `"torch"` and `"torch-eager"`. |
| `pipeline.quantization` | `"none"` | Quantization option passed to the pipeline. This app accepts `"none"` and `"fp8"`; hardware/runtime support still applies. |
| `pipeline.offload_ar` | `false` | Boolean option passed to the pipeline. |
| `pipeline.vae_core_frames` | `1024` | Positive integer option passed to the pipeline. |
| `pipeline.verify_hashes` | `true` | Whether the pipeline verifies hashes; must be a JSON boolean. |
| `data_dir` | `"data"` | Directory for the app database, logs, uploads, and generated artifacts. A relative path is resolved from the directory containing `config.local.json`. Back up this directory to preserve work. |
| `host` | `"127.0.0.1"` | Network interface address for the web server. The default listens on this machine only. Use `"0.0.0.0"` only when intentionally making the service reachable through network interfaces, such as for trusted LAN access. |
| `port` | `7860` | Web server port, integer from 1 to 65535. Keep it consistent with any WSL/Windows port forwarding. |
| `allowed_hosts` | `["127.0.0.1", "localhost", "[::1]"]` | Allowed HTTP Host names/IP literals. Add the exact hostname or IP used in the browser URL when needed. This is not client-IP filtering or a firewall, and `"*"` is rejected. |
| `cache_dir` | Optional; unset | Optional model/runtime cache directory passed to the YuE worker. |

The complete template, including pinned model revisions and the default pipeline options, is in [`config.example.json`](../config.example.json). The internal test-only `engine` setting is not a supported config key.

## Cover, Motif, and optional paths

For normal generation, configure the YuE `python`, `model`, and `vae`. The setup assistant also prints the `abc_tools` path; the app can derive it when that key is `null`.

For audio-to-score transcription, configure both `sheetsage_python` and `sheetsage_model` using the exact values printed by `./setup.sh --stage cover`. SheetSage2 source/model files and its venv are separate from YuE and should remain outside the published app tree. Cover from an uploaded ABC does not require SheetSage2. Motif audio clipping also requires FFmpeg 6.1.x at `/usr/bin/ffmpeg`; see [INSTALL.md](INSTALL.md).

Example entries to merge into the existing JSON object (replace placeholders with actual paths):

```json
{
  "python": "/path/to/YuE/venv/bin/python",
  "abc_tools": "/path/to/YuE/skills/yue2-music/scripts/abc_tools.py",
  "sheetsage_python": "/path/to/sheetsage-venv/bin/python",
  "sheetsage_model": "/path/to/SheetSage2-standalone"
}
```

This is an illustrative fragment, not a complete configuration: preserve the required `model`, `vae`, and `device` keys and merge the values rather than replacing the whole file.

## LAN access and safety

The default `host` is loopback-only. For access from another device on a trusted LAN, configure the bind address and allowed request host separately, for example:

```json
{
  "host": "0.0.0.0",
  "port": 7860,
  "allowed_hosts": ["127.0.0.1", "localhost", "[::1]", "192.168.1.20", "studio-pc"]
}
```

Merge these settings into your existing file and replace the sample IP/name with the address/name used in the browser URL. If using WSL port forwarding, the forwarded port and destination must match the app's actual bind address and port. `host` controls where the server listens; `allowed_hosts` checks the HTTP Host header. Neither setting provides authentication. The app has no account system: use only a trusted private network and do not expose or forward it directly to the public internet. Do not use a wildcard host allow-list.

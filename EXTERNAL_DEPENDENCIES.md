# External dependencies and setup conditions

This guide covers software and model files that are **not included** in this
release and must be obtained and installed separately by each user. The
versions below are the versions/revisions used in the development and
functional checks recorded for this application; they are not a promise that
other versions work, a license-compliance review, or a grant of rights.

For staged installation and read-only diagnostics, use [INSTALL.md](INSTALL.md)
or [INSTALL.ja.md](INSTALL.ja.md). This file remains the version and terms
reference; the installation steps are maintained in those guides.

The application publisher does not warrant that an external component's terms
permit a particular user's purpose, use, or distribution. Before downloading,
installing, or using a component, the user must review the applicable terms at
the official source, confirm they cover the exact artifact and intended use,
and obtain any required permissions. This guidance does not waive or replace
third-party license conditions.

## Application environment

Install only the app requirements into the app's separate Python environment.
The table records the development environment used for the release checks;
`requirements.txt` remains the source for app runtime constraints.

| Component | Purpose | Verified version/constraint | Official source and terms |
|---|---|---|---|
| Python | App runtime | Python 3.10 | [Python downloads](https://www.python.org/downloads/), [license](https://docs.python.org/3/license.html) |
| FastAPI | HTTP API | 0.115.6 | [FastAPI](https://github.com/fastapi/fastapi), [license](https://github.com/fastapi/fastapi/blob/master/LICENSE) |
| Uvicorn | ASGI server | 0.34.0 | [Uvicorn](https://github.com/encode/uvicorn), [license](https://github.com/encode/uvicorn/blob/master/LICENSE.md) |
| AnyIO | Async runtime | requirement `<4.10`; verified 4.9.0 | [AnyIO source and license](https://github.com/agronholm/anyio) |
| HTTPX | Optional test client | requirement `>=0.27,<0.28`; verified 0.27.2 | [HTTPX source and license](https://github.com/encode/httpx) |
| Playwright Python | Optional browser tests | requirement `>=1.48,<2`; verified 1.63.0 | [Playwright Python](https://github.com/microsoft/playwright-python), [license](https://github.com/microsoft/playwright-python/blob/main/LICENSE); browser downloads have separate terms |

Transitive dependencies may resolve to different versions. This project does
not distribute an app virtual environment or lock the complete transitive
dependency graph. Users who redistribute their own environment or binaries
must inspect the actual packages and their notices.

## YuE2 generation environment

YuE inference runs in its own Python environment. The app runtime does not
download YuE code or weights; the opt-in setup assistant can obtain them from
their official sources after explicit confirmation. For installation and supported invocation, consult the
[official YuE repository](https://github.com/multimodal-art-projection/YuE)
and its [generation guide](https://github.com/multimodal-art-projection/YuE/blob/main/docs/generation.md).
The observed environment was:

| Component | Verified version/revision | Purpose | Official source and terms |
|---|---|---|---|
| `yue2-infer` | 0.1.6 | YuE2 inference code | [YuE source](https://github.com/multimodal-art-projection/YuE), [package metadata](https://github.com/multimodal-art-projection/YuE/blob/main/pyproject.toml), [LICENSE](https://github.com/multimodal-art-projection/YuE/blob/main/LICENSE), [NOTICE](https://github.com/multimodal-art-projection/YuE/blob/main/NOTICE) |
| PyTorch | 2.10.0+cu128; CUDA runtime 12.8 | Tensor/GPU runtime | [PyTorch](https://pytorch.org/), [license and third-party notices](https://github.com/pytorch/pytorch/blob/main/LICENSE) |
| Transformers | 4.57.6 | Model framework | [Transformers source and license](https://github.com/huggingface/transformers) |
| `huggingface_hub` | 0.36.2 | Model repository access | [Hugging Face Hub source and license](https://github.com/huggingface/huggingface_hub) |
| Safetensors | 0.7.0 | Model serialization | [Safetensors source and license](https://github.com/huggingface/safetensors) |
| Tiktoken | 0.12.0 | Tokenization | [Tiktoken source and license](https://github.com/openai/tiktoken) |
| NumPy | 2.2.6 | Numerical arrays | [NumPy source and license information](https://github.com/numpy/numpy) |
| SoundFile | 0.13.1 | Audio file I/O | [python-soundfile source and license](https://github.com/bastibe/python-soundfile) |
| Accelerate | 1.13.0 | Model execution support | [Accelerate source and license](https://github.com/huggingface/accelerate) |
| YuE ABC helper | Installed YuE checkout; exact source commit not recorded | Native ABC validation/conversion; called by path, not bundled here | [YuE repository](https://github.com/multimodal-art-projection/YuE), especially its `skills/yue2-music/scripts/abc_tools.py`; retain upstream notices |

The public example configuration uses these model references:

| Model artifact | Revision used by the recorded configuration | Official artifact and terms to check |
|---|---|---|
| YuE2-3B | `14fc6c6f146441b1dd6363fcb2e01e82a6914cb7` | [Exact revision](https://huggingface.co/m-a-p/YuE2-3B/commit/14fc6c6f146441b1dd6363fcb2e01e82a6914cb7); the page identifies CC BY-NC 4.0. Check the exact files, access terms, and any additional permission. |
| YuE2-Vae | `9a94e1d0ea9f8087e98f77fa88df4a4068104d2a` | [Model repository](https://huggingface.co/m-a-p/YuE2-Vae), [configured revision](https://huggingface.co/m-a-p/YuE2-Vae/tree/9a94e1d0ea9f8087e98f77fa88df4a4068104d2a); confirm the terms at that exact revision before use. |

YuE's inference-code terms do not determine the terms for model weights. Do
not infer commercial permission for weights from the inference package's
license.

## SheetSage2 transcription environment

Transcription runs in a separate Python environment and requires the
SheetSage2 source package and model files. They are not included here. The
following SheetSage2 revision was supplied by the application owner as the
**動作確認済みrevision / functionally checked revision**:

`488abe28ef4db3dbb056da19cb49d80f4b14bc61`

This is a runtime compatibility record only; it is **not** a finding that the
revision or its weights are license-compliant for any purpose. The official
revision page currently displays CC BY-NC 4.0 metadata. Users must inspect
the exact files and terms themselves and obtain any permissions required for
their intended use.

| Component | Verified version/revision | Purpose | Official source and terms |
|---|---|---|---|
| SheetSage2 | `488abe28ef4db3dbb056da19cb49d80f4b14bc61` (owner-supplied, functionally checked revision) | Audio-to-ABC transcription | [Exact revision](https://huggingface.co/m-a-p/SheetSage2/commit/488abe28ef4db3dbb056da19cb49d80f4b14bc61), [repository files/license](https://huggingface.co/m-a-p/SheetSage2/tree/488abe28ef4db3dbb056da19cb49d80f4b14bc61) |
| PyTorch | 2.8.0+cu126 | Tensor/GPU runtime | [PyTorch](https://pytorch.org/), [license and third-party notices](https://github.com/pytorch/pytorch/blob/main/LICENSE) |
| TorchAudio | 2.8.0+cu126 | Audio support | [TorchAudio](https://github.com/pytorch/audio); inspect the installed distribution's license/notices |
| Transformers | 4.45.2 | Model framework | [Transformers source and license](https://github.com/huggingface/transformers) |
| `huggingface_hub` | 0.36.0 | Model access | [Hugging Face Hub source and license](https://github.com/huggingface/huggingface_hub) |
| Safetensors | 0.5.3 | Model serialization | [Safetensors source and license](https://github.com/huggingface/safetensors) |
| NumPy | 1.24.3 | Numerical arrays | [NumPy source and license information](https://github.com/numpy/numpy) |
| MERT-v2-FullSong | `d8ba1c745e733b3908ce6ad16ebeb17ac7600a42` (recorded base-model revision) | SheetSage2 audio encoder | [Exact revision](https://huggingface.co/m-a-p/MERT-v2-FullSong/commit/d8ba1c745e733b3908ce6ad16ebeb17ac7600a42), [LICENSE](https://huggingface.co/m-a-p/MERT-v2-FullSong/blob/d8ba1c745e733b3908ce6ad16ebeb17ac7600a42/LICENSE), [third-party notices](https://huggingface.co/m-a-p/MERT-v2-FullSong/blob/d8ba1c745e733b3908ce6ad16ebeb17ac7600a42/THIRD_PARTY_NOTICES.md) |

The MERT revision's license identifies the checkpoint weights as CC BY-NC
4.0 and notes separate code/dependency terms. Check the exact license scope
and all accompanying notices.

## FFmpeg, Python, and GPU software

Motif audio clipping invokes `/usr/bin/ffmpeg`; the documented and checked
setup uses FFmpeg 6.1. FFmpeg is not included. Its applicable licensing can
depend on build options and linked components; inspect the exact build and
vendor notices you install.

- Official FFmpeg downloads: <https://ffmpeg.org/download.html>
- FFmpeg licensing guidance: <https://ffmpeg.org/legal.html>
- NVIDIA CUDA and driver components are separately installed and are not
  included. Consult the [CUDA Toolkit terms](https://docs.nvidia.com/cuda/eula/index.html)
  and the terms for the exact driver/toolkit distribution.

## Japanese / 日本語

この公開物には、SheetSage2、MERT、YuE2、YuE2-VAE、FFmpeg、各Python環境や
モデルファイルは含まれません。利用者が各公式配布元から別途取得・導入して
ください。上記の版・revisionはこのアプリで記録された動作確認情報であり、
ライセンス適合、特定目的への利用許諾、または別の版での動作を保証するもの
ではありません。

利用者は、取得・導入・利用の前に、対象ファイルの正確なrevisionに適用される
条件、アクセス要件、利用目的への適用可能性を公式配布元で確認し、必要な許諾を
取得してください。この案内は第三者ライセンス条件を免除・変更しません。

SheetSage2の `488abe28ef4db3dbb056da19cb49d80f4b14bc61` は、アプリ所有者から提示
された**動作確認済みrevision**として記録しています。ライセンス適合確認済み
という意味ではありません。提示revisionの[公式ページ](https://huggingface.co/m-a-p/SheetSage2/commit/488abe28ef4db3dbb056da19cb49d80f4b14bc61)
にはCC BY-NC 4.0の表示がありますが、利用者自身が対象コード・重みへの適用範囲と
必要な許諾を確認してください。

| 外部依存物 | 記録した動作確認版・revision | 公式配布元・条件確認先 |
|---|---|---|
| YuE推論コード `yue2-infer` | 0.1.6 | [YuE](https://github.com/multimodal-art-projection/YuE)、[LICENSE](https://github.com/multimodal-art-projection/YuE/blob/main/LICENSE)、[NOTICE](https://github.com/multimodal-art-projection/YuE/blob/main/NOTICE) |
| YuE2-3B | `14fc6c6f146441b1dd6363fcb2e01e82a6914cb7` | [対象revision](https://huggingface.co/m-a-p/YuE2-3B/commit/14fc6c6f146441b1dd6363fcb2e01e82a6914cb7) |
| YuE2-VAE | `9a94e1d0ea9f8087e98f77fa88df4a4068104d2a` | [対象revision](https://huggingface.co/m-a-p/YuE2-Vae/tree/9a94e1d0ea9f8087e98f77fa88df4a4068104d2a) |
| SheetSage2 | `488abe28ef4db3dbb056da19cb49d80f4b14bc61`（動作確認済み） | [対象revision](https://huggingface.co/m-a-p/SheetSage2/commit/488abe28ef4db3dbb056da19cb49d80f4b14bc61) |
| MERT-v2-FullSong | `d8ba1c745e733b3908ce6ad16ebeb17ac7600a42` | [対象revisionと条件](https://huggingface.co/m-a-p/MERT-v2-FullSong/commit/d8ba1c745e733b3908ce6ad16ebeb17ac7600a42) |
| FFmpeg | 6.1 | [公式配布](https://ffmpeg.org/download.html)、[ライセンス情報](https://ffmpeg.org/legal.html) |
| NVIDIA CUDA／ドライバー | ホスト側で別途導入。版は環境依存 | [CUDA利用条件](https://docs.nvidia.com/cuda/eula/index.html) |

アプリの0BSDライセンスは、これら外部依存物やモデル、入力素材、生成音声の権利を
付与するものではありません。生成音声も自動的に0BSDまたはパブリックドメインに
なるものではありません。

# 外部依存物と導入条件

[English](EXTERNAL_DEPENDENCIES.md)

このガイドは、この公開物に含まれず、利用者が別途取得・導入するソフトウェアとモデルファイルを扱います。以下のバージョンとrevisionは、このアプリの開発時および動作確認時に使用したものです。他の版での動作、ライセンス条件への適合、利用権の付与を示すものではありません。

段階的な導入と読み取り専用の環境診断は、[日本語導入ガイド](INSTALL.ja.md)または[英語版導入ガイド](INSTALL.md)を参照してください。この文書はバージョンと利用条件の確認先をまとめ、導入手順は各ガイドで説明します。

アプリの公開者は、外部コンポーネントの条件が利用者の目的・利用方法・再配布を認めることを保証しません。取得・導入・利用の前に、利用者自身が公式配布元で対象となる正確な成果物の条件を確認し、目的への適用範囲を確かめ、必要な許諾を取得してください。この案内によって第三者のライセンス条件が免除または変更されることはありません。

## アプリ環境

アプリ用の独立したPython環境には、アプリの依存パッケージだけを導入してください。下表はリリース確認で使用した開発環境を記録しています。実行時に必要な制約は `requirements.txt` が基準です。

| コンポーネント | 用途 | 動作確認版・条件 | 公式配布元・条件 |
|---|---|---|---|
| Python | アプリ実行環境 | Python 3.10 | [Python配布](https://www.python.org/downloads/)、[ライセンス](https://docs.python.org/3/license.html) |
| FastAPI | HTTP API | 0.115.6 | [FastAPI](https://github.com/fastapi/fastapi)、[ライセンス](https://github.com/fastapi/fastapi/blob/master/LICENSE) |
| Uvicorn | ASGIサーバー | 0.34.0 | [Uvicorn](https://github.com/encode/uvicorn)、[ライセンス](https://github.com/encode/uvicorn/blob/master/LICENSE.md) |
| AnyIO | 非同期実行環境 | 条件 `<4.10`、確認版 4.9.0 | [AnyIOソースとライセンス](https://github.com/agronholm/anyio) |
| HTTPX | 任意のテストクライアント | 条件 `>=0.27,<0.28`、確認版 0.27.2 | [HTTPXソースとライセンス](https://github.com/encode/httpx) |
| Playwright Python | 任意のブラウザテスト | 条件 `>=1.48,<2`、確認版 1.63.0 | [Playwright Python](https://github.com/microsoft/playwright-python)、[ライセンス](https://github.com/microsoft/playwright-python/blob/main/LICENSE)。ブラウザ本体のダウンロードには別の条件があります。 |

推移依存パッケージは異なるバージョンで解決される場合があります。このプロジェクトはアプリの仮想環境を配布せず、推移依存パッケージ全体も固定していません。独自に環境やバイナリを再配布する場合は、実際に含めるパッケージと通知を確認してください。

## YuE2生成環境

YuE推論はアプリとは別のPython環境で実行します。アプリ本体の実行時にはYuEのコードや重みをダウンロードしません。任意で使えるセットアップ支援スクリプトは、明示的な確認を得て公式配布元から取得できます。導入方法とサポートされる実行方法は、[公式YuEリポジトリ](https://github.com/multimodal-art-projection/YuE)および[公式生成ガイド](https://github.com/multimodal-art-projection/YuE/blob/main/docs/generation.md)を参照してください。動作確認で使用した環境は次のとおりです。

| コンポーネント | 動作確認版・revision | 用途 | 公式配布元・条件 |
|---|---|---|---|
| `yue2-infer` | 0.1.6 | YuE2推論コード | [YuEソース](https://github.com/multimodal-art-projection/YuE)、[パッケージ定義](https://github.com/multimodal-art-projection/YuE/blob/main/pyproject.toml)、[LICENSE](https://github.com/multimodal-art-projection/YuE/blob/main/LICENSE)、[NOTICE](https://github.com/multimodal-art-projection/YuE/blob/main/NOTICE) |
| PyTorch | 2.10.0+cu128、CUDAランタイム12.8 | テンソル・GPU実行環境 | [PyTorch](https://pytorch.org/)、[ライセンスと第三者通知](https://github.com/pytorch/pytorch/blob/main/LICENSE) |
| Transformers | 4.57.6 | モデルフレームワーク | [Transformersソースとライセンス](https://github.com/huggingface/transformers) |
| `huggingface_hub` | 0.36.2 | モデルリポジトリへのアクセス | [Hugging Face Hubソースとライセンス](https://github.com/huggingface/huggingface_hub) |
| Safetensors | 0.7.0 | モデルデータのシリアライズ | [Safetensorsソースとライセンス](https://github.com/huggingface/safetensors) |
| Tiktoken | 0.12.0 | トークン化 | [Tiktokenソースとライセンス](https://github.com/openai/tiktoken) |
| NumPy | 2.2.6 | 数値配列処理 | [NumPyソースとライセンス情報](https://github.com/numpy/numpy) |
| SoundFile | 0.13.1 | 音声ファイルの入出力 | [python-soundfileソースとライセンス](https://github.com/bastibe/python-soundfile) |
| Accelerate | 1.13.0 | モデル実行支援 | [Accelerateソースとライセンス](https://github.com/huggingface/accelerate) |
| YuE ABC helper | インストールしたYuEチェックアウト。ソースの正確なcommitは未記録 | ABC検証・変換。パスを指定して呼び出し、ここには同梱しません。 | [YuEリポジトリ](https://github.com/multimodal-art-projection/YuE)、特に `skills/yue2-music/scripts/abc_tools.py`。上流の通知を維持してください。 |

公開用の設定例では、次のモデルを指定しています。

| モデル | 設定に記録されたrevision | 公式配布物と確認する条件 |
|---|---|---|
| YuE2-3B | `14fc6c6f146441b1dd6363fcb2e01e82a6914cb7` | [対象revision](https://huggingface.co/m-a-p/YuE2-3B/commit/14fc6c6f146441b1dd6363fcb2e01e82a6914cb7)。ページにはCC BY-NC 4.0の表示があります。対象ファイル、アクセス条件、追加許諾の有無を確認してください。 |
| YuE2-Vae | `9a94e1d0ea9f8087e98f77fa88df4a4068104d2a` | [モデルリポジトリ](https://huggingface.co/m-a-p/YuE2-Vae)、[設定revision](https://huggingface.co/m-a-p/YuE2-Vae/tree/9a94e1d0ea9f8087e98f77fa88df4a4068104d2a)。利用前に対象revisionの条件を確認してください。 |

YuE推論コードの条件から、モデル重みの条件を判断することはできません。推論パッケージのライセンスを根拠に、重みの商用利用が許可されると解釈しないでください。

## SheetSage2採譜環境

音源の採譜には、SheetSage2のソースパッケージとモデルファイルが必要です。これらは本公開物に含まれません。次のSheetSage2 revisionは、アプリ所有者から提示された**動作確認済みrevision**です。

`488abe28ef4db3dbb056da19cb49d80f4b14bc61`

これは実行時の互換性を記録したものであり、このrevisionや重みがいかなる目的にもライセンス適合するという判断ではありません。公式revisionページには現在CC BY-NC 4.0のメタデータが表示されています。利用者は対象ファイルと条件を確認し、利用目的に必要な許諾を取得してください。

| コンポーネント | 動作確認版・revision | 用途 | 公式配布元・条件 |
|---|---|---|---|
| SheetSage2 | `488abe28ef4db3dbb056da19cb49d80f4b14bc61`（所有者提示、動作確認済みrevision） | 音源からABCへの採譜 | [対象revision](https://huggingface.co/m-a-p/SheetSage2/commit/488abe28ef4db3dbb056da19cb49d80f4b14bc61)、[リポジトリのファイルとライセンス](https://huggingface.co/m-a-p/SheetSage2/tree/488abe28ef4db3dbb056da19cb49d80f4b14bc61) |
| PyTorch | 2.8.0+cu126 | テンソル・GPU実行環境 | [PyTorch](https://pytorch.org/)、[ライセンスと第三者通知](https://github.com/pytorch/pytorch/blob/main/LICENSE) |
| TorchAudio | 2.8.0+cu126 | 音声処理 | [TorchAudio](https://github.com/pytorch/audio)。インストールした配布物のライセンスと通知を確認してください。 |
| Transformers | 4.45.2 | モデルフレームワーク | [Transformersソースとライセンス](https://github.com/huggingface/transformers) |
| `huggingface_hub` | 0.36.0 | モデルへのアクセス | [Hugging Face Hubソースとライセンス](https://github.com/huggingface/huggingface_hub) |
| Safetensors | 0.5.3 | モデルデータのシリアライズ | [Safetensorsソースとライセンス](https://github.com/huggingface/safetensors) |
| NumPy | 1.24.3 | 数値配列処理 | [NumPyソースとライセンス情報](https://github.com/numpy/numpy) |
| MERT-v2-FullSong | `d8ba1c745e733b3908ce6ad16ebeb17ac7600a42`（記録されたベースモデルrevision） | SheetSage2の音声エンコーダー | [対象revision](https://huggingface.co/m-a-p/MERT-v2-FullSong/commit/d8ba1c745e733b3908ce6ad16ebeb17ac7600a42)、[LICENSE](https://huggingface.co/m-a-p/MERT-v2-FullSong/blob/d8ba1c745e733b3908ce6ad16ebeb17ac7600a42/LICENSE)、[第三者通知](https://huggingface.co/m-a-p/MERT-v2-FullSong/blob/d8ba1c745e733b3908ce6ad16ebeb17ac7600a42/THIRD_PARTY_NOTICES.md) |

MERTの対象revisionのライセンスには、チェックポイントの重みがCC BY-NC 4.0であることと、コード・依存物には別の条件があることが記載されています。適用範囲と付属通知を確認してください。

## FFmpeg、Python、GPUソフトウェア

Motifの音源区間切り出しは `/usr/bin/ffmpeg` を呼び出します。文書化および確認済みの導入ではFFmpeg 6.1を使用します。FFmpegは同梱されません。適用されるライセンスはビルドオプションやリンクされたコンポーネントによって異なる場合があるため、導入するビルドとベンダーの通知を確認してください。

- FFmpeg公式ダウンロード: <https://ffmpeg.org/download.html>
- FFmpegライセンス案内: <https://ffmpeg.org/legal.html>
- NVIDIA CUDAとドライバーは別途導入が必要で、本公開物には含まれません。[CUDA Toolkitの条件](https://docs.nvidia.com/cuda/eula/index.html)および実際に導入するドライバー・ツールキットの条件を確認してください。

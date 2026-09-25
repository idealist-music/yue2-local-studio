# Linux／WSL2 Ubuntuへの導入

[English](INSTALL.md) · [外部依存物の版と条件](EXTERNAL_DEPENDENCIES.md)

`./setup.sh` は対話形式で「アプリのみ」「YuE2通常生成まで」「SheetSage2を使うCover・Motifまで」を選べます。取得・導入の前に、配布元・導入先・容量目安・作業内容を示して確認します。`./setup.sh --doctor` は環境を変更せず、段階ごとに `OK`／`MISSING`／`MANUAL` を表示します。インストーラーは `sudo`、`apt`、システム領域への書き込みをしません。既存の `config.local.json`、モデル、完成済みvenvは上書きしません。ダウンロードが中断した場合は原因を解消して同じ段階を再実行します。外部ファイルはアプリのディレクトリ外に置いてください。

```bash
./setup.sh --stage app
./setup.sh --stage yue --external-dir /absolute/path/to/yue2-external
./setup.sh --stage cover --external-dir /absolute/path/to/yue2-external
./setup.sh --doctor
```

`yue` はアプリの導入も含み、`cover` はアプリとYuE2の導入も含みます。`--stage` を省略すると選択メニューが出ます。既存の公式YuEソースを使う場合は `--yue-dir /absolute/path/to/YuE` を指定できます。設定済みのYuE Pythonからも既存ソースを検出します。既存環境の版が異なる場合やディレクトリが不完全な場合は停止し、更新や削除はしません。Git操作は未取得の公式YuEリポジトリを `git clone` するときだけです。

## 1. アプリ本体と通常生成

先にPython 3.10以上、`venv`、`pip`を用意します。Ubuntuでは管理者がディストリビューションのパッケージ管理機能で `python3`、`python3-venv`、`python3-pip`、`git` を導入できます。アプリ用の `.venv` と `requirements.txt` の導入はスクリプトが確認後に実施します。

YuE2では[公式YuEリポジトリ](https://github.com/multimodal-art-projection/YuE)の `yue2-v0.1.6` タグを指定した外部ディレクトリへ複製し、専用venvで公式の `python -m pip install .` を実行します。[公式生成ガイド](https://github.com/multimodal-art-projection/YuE/blob/main/docs/generation.md)はPython 3.12で説明しています。パッケージ定義はPython 3.10以上で、当方の動作確認環境はPython 3.10、`yue2-infer` 0.1.6、PyTorch 2.10.0（CUDA 12.8ビルド）、Transformers 4.57.6です。スクリプトは利用可能なら `python3.12`、なければ `python3` を選びます。導入したPyTorchとGPUドライバーの組み合わせは[PyTorch公式の選択ページ](https://pytorch.org/get-started/locally/)で確認してください。

YuE2が示す標準条件はLinux、BF16対応のNVIDIA GPUと24 GBのVRAM、約24 GBの空きホストRAM、同時生成1件です。少ないVRAMでの設定はこのインストーラーの確認対象ではありません。Ubuntu／WSL2内で `nvidia-smi` を実行し、YuE用venvで `.../venv/bin/python -c 'import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.is_bf16_supported())'` を確認してください。WSL2ではWindows側の対応NVIDIAドライバーとGPU連携も必要です。ドライバーとシステムCUDAは自動導入しません。

アプリのワーカーはオフラインでモデルを読み込むため、[YuE2-3B](https://huggingface.co/m-a-p/YuE2-3B) と [YuE2-Vae](https://huggingface.co/m-a-p/YuE2-Vae) が必要です。スクリプトは `config.example.json` の固定revisionを指定して外部ディレクトリへ取得する選択肢を提示します。容量目安はそれぞれ約8～10 GiB、約0.6 GiBで、別にPythonパッケージとキャッシュ用の空き容量が必要です。`model`、`vae`、`python`、`abc_tools` の設定値を提案します。ABC補助ツールは公式ソース中の `YuE/skills/yue2-music/scripts/abc_tools.py` を確認し、アプリにコピーしません。
Hugging Faceの既存キャッシュは、指定revisionと完全な重みが確認できる場合だけ再利用し、その場合は設定中のモデルIDをそのまま使えます。

## 2. 音源からのCover・Motif採譜

音源から採譜するときだけ `./setup.sh --stage cover` を使います。ABCを直接使うCoverにはYuE2とABC補助ツールが必要ですが、SheetSage2は不要です。スクリプトはPython 3.10／3.11の別venvを作り、公式[SheetSage2](https://huggingface.co/m-a-p/SheetSage2)の動作確認済みrevision `488abe28ef4db3dbb056da19cb49d80f4b14bc61`（約0.25 GiB）と、指定された[MERT-v2-FullSong](https://huggingface.co/m-a-p/MERT-v2-FullSong)のrevision `d8ba1c745e733b3908ce6ad16ebeb17ac7600a42`（約2.6 GiB）を取得します。[公式SheetSage2手順](https://huggingface.co/m-a-p/SheetSage2/blob/main/README.md)に合わせてCUDA 12.6向けPyTorch／TorchAudio 2.8.0と、モデルの `requirements.txt` を専用venvに入れます。ワーカー用の統合モデルを作る際には、さらに約3 GiBのディスク容量と十分な空きRAMが必要です。

Hugging Faceがアクセスを拒否した場合は、両モデルの配布ページで必要な承認を済ませ、`<sheetsage-venv>/bin/hf auth login` を対話的に実行してから同じ段階を再実行してください。トークンはコマンド行、ログ、公開リポジトリ、`config.local.json` に書かないでください。各モデルの対象revisionに適用される条件と、利用目的に必要な許諾は利用者が確認します。動作確認済みrevisionという記録はライセンス適合の保証ではありません。

このアプリの採譜ワーカーは `SheetSage2.modeling_sheetsage2.SheetSage2Model` を直接インポートし、ローカル統合モデルを `from_pretrained(..., local_files_only=True)` で読み込み、`transcribe(..., melody_only=True)` を使います。スクリプトはソースを `<external>/SheetSage2/`、統合モデルを隣の `<external>/SheetSage2-standalone/` に置き、直接インポートと `melody_only` 対応を確認します。一般的な `AutoModel` の例だけでアプリが使用可能とは判定しません。設定候補は `sheetsage_python` と `sheetsage_model` です。モデルは公開用ディレクトリへ保存しません。

## 3. FFmpegとシステム側の確認

SheetSage2の公式音声手順ではFFmpeg 6.1と対応する共有ライブラリが必要です。現行Motifの区間切り出しは **`/usr/bin/ffmpeg` 固定**です。別の場所に実行ファイルを置いても、そのままではMotifの切り出しは動きません。診断はその固定パスの版と `ldd` の不足ライブラリを確認します。Coverの音源採譜はSheetSage2側の音声処理に依存します。ABC直接入力のCoverではFFmpegを呼びません。

```bash
command -v ffmpeg
/usr/bin/ffmpeg -version
ldd /usr/bin/ffmpeg | grep 'not found'
command -v ffprobe && ffprobe -version
```

Ubuntu／WSL2では管理者が `sudo apt update` と `sudo apt install ffmpeg` で導入できますが、Ubuntuの版によってFFmpeg 6.1以外が入るため、導入後に必ず版と共有ライブラリを確認してください。6.1がない場合は管理者が信頼できる配布物を `/usr/bin/ffmpeg` と対応ライブラリで用意する必要があります。Windowsの `ffmpeg.exe` やPATH上の別パスだけではMotifの条件を満たしません。[FFmpeg公式配布情報](https://ffmpeg.org/download.html)も参照してください。

## 完了確認

既存の `config.local.json` は編集せず、必要なパスを表示します。新規の場合だけ、`config.example.json` を元に設定ファイルを作るか確認します。`model`、`vae`、両revision、`device`、`python`、`abc_tools`、`sheetsage_python`、`sheetsage_model` を確認してください。設定ファイルとモデルはGitに含めないでください。

```bash
./setup.sh --doctor
./setup.sh --load-check yue    # アプリのYuEワーカーを読み込む。生成なし
./setup.sh --load-check sheet  # オフライン統合モデルをCPUで読み込む。採譜なし
./run.sh
```

ロード確認は任意で、明示確認後に行います。時間とメモリを多く使用します。SheetSage2のCPUロード成功はGPU採譜や音楽品質の保証ではありません。通常の診断結果とロード確認結果は別に扱ってください。既定ポートは7860です。操作とLAN設定は[README.ja.md](README.ja.md)、Coverの流れは[README-COVERS.ja.md](README-COVERS.ja.md)、外部依存物の条件は[EXTERNAL_DEPENDENCIES.md](EXTERNAL_DEPENDENCIES.md)を参照してください。

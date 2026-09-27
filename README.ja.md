# YuE2 Local Studio

YuE2の生成ジョブと結果を管理するローカルWebアプリです。ABCを使ったCover、フレーズから作曲するMotif、ABC/MIDIの往復編集にも対応します。アプリ本体、YuE2、SheetSage2はそれぞれ別のPython環境で動かします。

アプリのソースにはモデル重み、YuE2、SheetSage2、MERT、VAE、FFmpeg、公式YuE ABC補助ツールを含みません。公式配布元から別途取得し、ローカルパスを設定してください。導入は[日本語導入ガイド](docs/INSTALL.ja.md)、バージョン・revisionと利用条件の確認先は[外部依存物ガイド](docs/EXTERNAL_DEPENDENCIES.ja.md)を参照してください。アプリ実行時にモデルをダウンロードすることはありません。任意のセットアップ支援機能は、確認後に固定revisionの外部ファイルを取得します。

## 必要条件

- 動作確認対象はLinux／WSL2 Ubuntuです。その他の環境は確認していません。
- アプリ環境はPython 3.10で動作確認しています。アプリ用環境には`requirements.txt`のパッケージのみを導入します。
- YuE2には専用Python環境、PyTorch／CUDA、モデル重み、VAEが必要です。GPU生成には対応GPUと、モデル・設定に応じた十分なVRAMが必要です。CPUは限定的な確認用途であり、実用的な楽曲生成を保証しません。
- SheetSage2で音源を採譜するには、別のPython環境、モデルパッケージと重み、MERT-v2-FullSong、対応GPUが必要です。
- **Coverの音源採譜とMotifには、共有ライブラリを含むFFmpeg 6.1.xが必要です。** Motifは**`/usr/bin/ffmpeg`を直接実行**するため、PATH上の別の場所にあるだけではMotifで使えません。

アカウント機能や認証はありません。localhostまたは信頼できるプライベートネットワーク内で使用し、インターネットへ直接公開しないでください。LAN接続には、非公開の`config.local.json`で待受先と許可ホストを明示的に設定します。

## セットアップ

このディレクトリで対話型セットアップを実行し、アプリのみ、YuE2通常生成、Cover／Motif用SheetSage2の各段階を選びます。

```bash
./setup.sh
./setup.sh --stage app
./setup.sh --stage yue --external-dir /absolute/path/to/yue2-external
./setup.sh --stage cover --external-dir /absolute/path/to/yue2-external
./setup.sh --doctor
```

`--stage yue`にはアプリ本体の導入も含まれ、`--stage cover`にはアプリとYuE2の導入も含まれます。セットアップは取得元、導入先、容量目安、実行内容を表示してから、ダウンロードやパッケージ導入を確認します。既存環境を検出・再利用し、アプリが必要とするパスを表示します。`config.local.json`がない場合は作成を提案しますが、**すでに存在する場合は値を保持し、表示したパスを自動追記しません**。後の段階を実行したら、表示された`python`、`model`、`vae`、`abc_tools`、`sheetsage_python`、`sheetsage_model`を既存設定の対応キーへ手動で反映してください。ファイル全体を置き換えず、`host`、`port`、`allowed_hosts`など他の設定は保持してください。FFmpeg 6.1.xは管理者による別途導入が必要で、版と共有ライブラリを確認します。コマンド例と設定サンプルは[導入ガイド](docs/INSTALL.ja.md)を参照してください。外部配布物の利用条件と必要なアクセス許可は、各配布元で確認してください。

アプリの起動:

```bash
./run.sh
```

既定のポートは7860です。既定設定では <http://127.0.0.1:7860> を開き、終了はCtrl+Cです。データベース、ログ、アップロード音源、生成物は`data/`（または設定した`data_dir`）に保存されます。必要なデータはバックアップしてください。

LANへ接続するには、非公開の`config.local.json`で`host`と`allowed_hosts`を明示的に設定します。認証はないため、信頼できるネットワークだけで使用し、ポートをインターネットへ転送しないでください。

## 機能と制限

- YuE2による生成、ジョブ履歴、生成結果の保存。
- YuE2 native ABCまたは採譜音源を使うCover。採譜結果は生成前に確認が必要です。歌詞認識や自動作詞は行いません。[Cover手順](docs/README-COVERS.ja.md)
- 音源の指定区間を採譜して新曲に取り入れるMotif。[Motif手順](docs/README-MOTIF.ja.md)
- ABC譜の編集とMIDI往復編集。[MIDI手順](docs/README-MIDI-ROUNDTRIP.ja.md)

ABC変換の対応範囲は公式YuE補助ツールが受け付ける形式に限られ、任意のABCとの互換性は保証しません。MIDI往復編集では、ABCで表現できない演奏情報が失われる場合があります。生成音声を試聴し、取り込んだ譜面も確認してください。

## データとプライバシー

データベース、ログ、アップロード音源、歌詞、生成物は実行時データであり、ソースツリーには含まれません。公開の不具合報告に個人の音源、歌詞、設定、ログ、データベースを添付しないでください。診断情報を共有する前に、機密情報が含まれていないか確認してください。

## 開発時の確認

任意のアプリ開発用依存物は、アプリ環境で`python -m pip install -r requirements-dev.txt`を実行して導入できます。同梱テストはアプリとMIDIコードを対象とします。YuE、SheetSage2、ブラウザ、実音源が必要なテストは公開用テスト範囲に含まれません。この公開ツリーはクリーン環境ではテストされていません。

## ライセンス

`studio/`、`static/`、アプリ独自のルートスクリプトと設定テンプレート（`worker.py`、`transcribe_worker.py`、`audio_probe.py`、`run.sh`、`setup.sh`、`setup_assistant.py`、`prepare_sheetsage.py`、`config.example.json`）、`tests/`にあるアプリ独自コードにはBSD Zero Clause License（SPDX: 0BSD）を適用します。本文はルートの[LICENSE](LICENSE)にあります。この許諾はアプリ独自コードだけに適用され、YuE/YuE2のコード、外部ライブラリ、モデルコード・重み、別途導入するソフトウェアのライセンスを変更しません。[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)には公開物に含まれる第三者素材の通知範囲を、[外部依存物ガイド](docs/EXTERNAL_DEPENDENCIES.ja.md)には別途導入するものの公式配布元と条件確認先を記載しています。

YuE推論コード、YuE2/VAE、SheetSage2、MERT、その他のモデルファイルには配布元ごとの条件が適用されます。アプリ公開者は外部条件が個々の利用目的を許可することや、必要な許諾取得を保証しません。利用者は対象ファイルの条件と必要な許諾を確認してください。アプリの0BSDライセンスからモデルの商用利用権を推測しないでください。アプリのライセンスは入力作品や生成音楽の権利を定めず、生成音声が自動的に0BSDまたはパブリックドメインになることもありません。モデル条件、入力素材の権利、適用法令を別途確認してください。

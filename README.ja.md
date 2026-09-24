# YuE2 Local Studio

YuE2を別のPython環境で動かす、ローカル向けの音楽制作Webアプリです。通常生成、ABCを使ったカバー、フレーズからの作曲、ABC/MIDI往復編集に対応します。アプリ本体、YuE2、SheetSage2は別々の環境で動かします。

アプリ用の環境は `./setup.sh` で作成します。`config.example.json` を `config.local.json` にコピーし、YuE2のPython、モデルとVAEのパス・revisionを設定してください。アプリはポート7860で起動します。詳細なセットアップと利用上の制約は [英語版README](README.md)、[Cover手順](README-COVERS.md)、[Motif手順](README-MOTIF.md)、[MIDI往復編集手順](README-MIDI-ROUNDTRIP.md) を参照してください。

## ライセンス

`studio/`、`static/`、アプリ独自のルートスクリプトと設定テンプレート（`worker.py`、`transcribe_worker.py`、`audio_probe.py`、`run.sh`、`setup.sh`、`config.example.json`）、`tests/` にあるアプリ独自コードには BSD Zero Clause License（SPDX: 0BSD）を適用します。本文はルートの [LICENSE](LICENSE) にあります。この許諾はアプリ独自コードだけに適用されます。YuE/YuE2のコード、外部ライブラリ、モデルコード・重み、その他の別途インストールするソフトウェアのライセンスを変更しません。

SheetSage2、MERT、YuE2、YuE2-VAE、FFmpeg、各実行環境は公開物に含まれず、利用者が公式配布元から別途取得・導入します。版・revisionと条件確認先は[外部依存物ガイド](EXTERNAL_DEPENDENCIES.md)を参照してください。当方は外部条件への適合や個々の利用目的に対する許諾を保証しません。利用者は対象revisionの条件を確認し、必要な許諾を取得してください。この案内は第三者ライセンス条件を免除・変更しません。

このアプリのライセンスは入力作品や生成音楽の権利を定めません。生成音声が自動的に0BSDまたはパブリックドメインになることもありません。モデル条件、入力素材の権利、適用法令を別に確認してください。[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)には公開物に含まれる第三者素材の通知範囲を記載しています。

# 公開用ツリー監査

監査対象: `yue2-local-studio-public-release/` のみ。読み取り専用監査で、変更はこの報告書の作成のみ。ランタイム環境のクリーンインストール・起動テストではない。

## 結果

- **大容量・生成物:** 49ファイルを確認。最大は `studio/midi_score.py` 30,654 bytes、1 MiB以上のファイルなし。音源・モデル重み・DB・ログ・キャッシュ・`.env`・`config.local.json`・`data/`・`uploads/`・`outputs/`は見つからなかった。`tests/fake_worker.py`は実音楽ではない合成サイン波をテスト時に生成する旨を明記している（同ファイル1行目）。例示歌詞とABC/MIDIデータもテストコード内の小さな人工値。
- **秘密情報・マシン情報:** トークン、secret、password、API key、Authorization、絶対パス、IPv4を検索。実資格情報、`/home/<user>`等の個人環境パス、LAN IPは検出なし。該当文字列はコード上の`secrets`/`preview_token`、説明語、テスト用ループバックIP、および`/absolute/path/to/...`というプレースホルダーで、秘密値ではない。`.env.example`は設定ファイルではなく、アプリが自動読込しない旨の説明（1–3行）。
- **リンク:** シンボリックリンクなし。公開ツリー外を指すリンクなし。公開ツリー内に`.git`ディレクトリなし（Gitコマンドは実行していない）。
- **インポート・起動参照:** `run.sh`は同梱の`studio.main`を起動し（`run.sh` 3–9行）、`setup.sh`は同梱の`requirements.txt`を使う（`setup.sh` 3–8行）。Python 23ファイルをAST構文解析し、`bash -n`で両シェルスクリプトを検査、いずれも成功。静的確認上、`studio/`内相対import、`worker.py`、`transcribe_worker.py`、`audio_probe.py`、静的ファイルの参照先は存在する。外部のYuE/SheetSage2パッケージ、モデル、公式YuE ABCヘルパーが実環境になければ該当機能は利用できない設計。
- **外部依存手順との整合:** YuEワーカーは `yue2.YuE2Pipeline.from_pretrained`、全曲プランでは`cot="full"`を使用（`worker.py` 59–65、79–83行）。SheetSage2ワーカーはローカル`SheetSage2.modeling_sheetsage2.SheetSage2Model`を直接importし、`local_files_only=True`と`melody_only=True`を使う（`transcribe_worker.py` 49–64行）；Cover案内も同方式を説明（`README-COVERS.md` 21–27行）。ガイドのSheetSage2 `488abe28ef4db3dbb056da19cb49d80f4b14bc61` は**動作確認済みrevision**との記録に留まり、ライセンス適合確認済みとはしていない（`EXTERNAL_DEPENDENCIES.md` 70–85行）。FFmpegの`/usr/bin/ffmpeg`固定呼出しと6.1の案内も一致（`studio/motif_queue.py` 46行、`README-COVERS.md` 39–41行）。
- **ライセンス・通知:** `LICENSE`は0BSD本文。`README.md` 56–60行、`README.ja.md` 7–13行および`THIRD_PARTY_NOTICES.md` 23–35行は0BSDの対象をアプリ独自部分に限定し、外部依存・モデル・入力・生成物を区別。`EXTERNAL_DEPENDENCIES.md`は別途取得する依存物と公式条件確認先、利用者自身による確認・許諾取得を明記（1–14行）。SheetSage2/MERT/YuE2/VAE、FFmpegと実行環境は非同梱の案内。公開ツリー内の第三者コード、ライブラリバンドル、CDN資産、フォント、画像・音声・バイナリはファイル棚卸しで確認されず、第三者ライセンス全文の追加が必要な同梱対象は見つからなかった。第三者コードの全上流との逐語的な来歴比較は本監査では行っていない。
- **READMEからの再現性:** アプリ環境の基本手順（`./setup.sh`、`config.example.json`を複製して設定、`./run.sh`、7860番ポート）は`README.md` 17–37行にある。依存条件は一部制約/固定のみで完全lockfileはなく、`EXTERNAL_DEPENDENCIES.md` 31–34行も依存解決が変わり得ると明記。YuE2/SheetSage2/モデル/FFmpegは公式手順を参照する設計で、SheetSage2案内は「公式配布元の現行手順」とし具体的な環境構築コマンドを含まない（`README-COVERS.md` 23–27行）。したがって**文書を参考に導入先を設定することはできるが、全外部環境をREADMEだけでクリーン再現できるとは確認できない**。README自身もクリーン環境未テストと明記（`README.md` 48–50行）。
- **配布・操作:** この監査でGit操作、GitHub認証/API、アップロード、ネットワーク公開、依存インストール、GPU生成は実施していない。

## 公開判断上の残件

この静的監査では、今回のツリーに混入した秘密情報・ユーザーデータ・大容量バイナリ・未通知の同梱第三者資産は見つからず、直ちに除外すべきファイルは特定されなかった。残る制約は、外部モデル/環境の導入が利用者の別作業であること、依存全体がlockされていないこと、クリーン環境での実起動を未確認であること。SheetSage2 revisionのライセンス適合性は本監査の対象外であり、確認済みとは扱わない。

## フェーズ4最終検証（2026-09-24）

監査確認後、公開ツリーを `/tmp` 配下の一時ディレクトリへコピーして検証した。公開ツリーそのものへテストデータ、DB、ログ、モデル、生成音声は作成していない。

- `python -m compileall`（`studio/`、`tests/`、ルートのPythonワーカー）と `bash -n setup.sh run.sh`: **成功**。
- アプリ用既存venvの依存を使い、一時コピーを `--test-engine` でUvicorn起動: **成功**。トップページ `GET /`、`GET /api/health`、`GET /static/app.js` はHTTP 200。healthは `queue_state=ready`、`ready=true`、`worker_state=not_started` を返した。GPU、モデル、外部音源は使用していない。
- `tests.test_midi_codec`、`tests.test_midi_roundtrip`、`tests.test_midi_routes`: **5件成功**。
- `tests.test_studio`: **4件成功**。
- 最終棚卸し: シンボリックリンク、1 MiB超ファイル、`.env`実体、設定実体、DB、ログ、モデル重み、音源候補は**なし**。READMEのローカル参照リンク欠落も**なし**。秘密情報・個人環境パス・LANアドレスの検出も**なし**。

未実施・制約: クリーンな新規Python環境の作成や依存インストール、YuE2/SheetSage2/MERT/VAE/FFmpegを導入した実生成・実採譜、ブラウザ自動操作、LAN経由の確認は行っていない。外部依存が未導入の場合の実際のモデル処理エラー表示は、外部環境を変更しない制約のため未実施である。Git/GitHub操作、認証、アップロード、GPU生成は行っていない。

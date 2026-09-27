# ローカル設定（`config.local.json`）

`config.local.json`には、このPC固有のパスや実行設定を保存します。ローカルパスやネットワーク設定が含まれるため、Gitの追跡対象外です。公開しないでください。追跡対象の[`config.example.json`](../config.example.json)はテンプレートであり、アプリが自動的に読み込む設定ファイルではありません。

## 作成と更新

必要なセットアップ段階を実行し、**Suggested config values**に表示された絶対パスを使います。セットアップは`config.local.json`がまだない場合だけ作成を提案し、既存ファイルへ新しい候補を自動で統合しません。既存の設定を残したまま、該当するキーを手動で追加・更新してください。設定ファイルがない場合は、次のようにテンプレートをコピーして使えます。

```bash
cp config.example.json config.local.json
```

その後、YuEのパスや、必要な場合はCover／Motif用のパスを編集します。JSONにはコメントや末尾のカンマを入れられません。未対応のキーはエラーになるため、独自のキーを追加しないでください。編集後はアプリを再起動します。

`./setup.sh --doctor`で、環境を変更せずパスや導入状況を確認できます。任意のワーカーロード確認は[INSTALL.ja.md](INSTALL.ja.md)を参照してください。

## 設定項目

以下のパスはLinux／WSLのパスです。`python`にはアプリの`.venv`ではなくYuE2用環境を指定します。YuEとSheetSage2には別々のPython環境が必要です。

| キー | 必須／既定値 | 説明 |
| --- | --- | --- |
| `python` | 必須。絶対パス | YuE2用venvのPython実行ファイル。 |
| `model` | 必須 | YuE2モデルのリポジトリIDまたはローカルスナップショットのパス。ワーカーはローカルファイルを読み込み、実行時に不足ファイルをダウンロードしません。利用可能なスナップショットを指定してください。 |
| `vae` | 必須 | YuE2 VAEのリポジトリIDまたはローカルスナップショットのパス。オフラインで読み込める必要があります。 |
| `device` | 必須 | YuE実行環境へ渡すデバイス文字列。一般的には`cuda:0`です。GPU、ドライバー、PyTorchビルド、空きメモリの互換性が必要です。 |
| `revision` | 任意。テンプレートには固定値あり | YuE2モデルのrevisionとして実行環境へ渡します。ローカルのスナップショットと一致させてください。 |
| `vae_revision` | 任意。テンプレートには固定値あり | VAEのrevisionとして実行環境へ渡します。ローカルのスナップショットと一致させてください。 |
| `abc_tools` | 任意。テンプレートは`null` | 公式YuEの`abc_tools.py`の絶対パス。省略または`null`の場合、YuE用Python環境からアプリがパスを推定します。自動検出できない場合は明示してください。 |
| `sheetsage_python` | 任意。`null` | SheetSage2専用venvのPython実行ファイルの絶対パス。Cover／Motifの音源採譜に必要です。通常生成やABC直接入力のCoverには不要です。 |
| `sheetsage_model` | 任意。`null` | アプリが`SheetSage2Model`を直接読み込むための、ローカルのstandaloneモデルの絶対パス。音源採譜に必要です。アプリ実行時にはダウンロードされません。 |
| `pipeline` | 任意。下記が既定値 | YuEパイプラインへ渡す実行オプション。このアプリと導入済みYuEの対応が確認されたキー・値だけを使ってください。 |
| `pipeline.memory_budget_gib` | `24.0` | YuEパイプラインへ渡すメモリ予算。2より大きい有限数が必要です。 |
| `pipeline.backend` | `"torch"` | パイプラインへ渡すバックエンド。このアプリが受け付ける値は`"torch"`と`"torch-eager"`です。 |
| `pipeline.quantization` | `"none"` | パイプラインへ渡す量子化設定。このアプリが受け付ける値は`"none"`と`"fp8"`です。ハードウェアと実行環境の対応も必要です。 |
| `pipeline.offload_ar` | `false` | パイプラインへ渡す真偽値のオプションです。 |
| `pipeline.vae_core_frames` | `1024` | パイプラインへ渡す正の整数オプションです。 |
| `pipeline.verify_hashes` | `true` | パイプラインによるハッシュ検証の有無。JSONの真偽値で指定します。 |
| `data_dir` | `"data"` | DB、ログ、アップロード音源、生成物の保存先。相対パスは`config.local.json`があるディレクトリを基準に解決します。データを残すにはこのディレクトリをバックアップしてください。 |
| `host` | `"127.0.0.1"` | Webサーバーの待受アドレス。既定値はこのPC内だけで待ち受けます。信頼できるLANなどから到達させる場合に限り、必要性を確認した上で`"0.0.0.0"`を指定します。 |
| `port` | `7860` | Webサーバーのポート。1～65535の整数です。WSL／Windowsのポート転送を使う場合は、実際の待受ポートと一致させてください。 |
| `allowed_hosts` | `["127.0.0.1", "localhost", "[::1]"]` | HTTP Hostヘッダーで許可するホスト名・IPリテラルの一覧です。必要ならブラウザURLで使う名前・IPを追加します。接続元IPの制限やファイアウォールではなく、`"*"`は指定できません。 |
| `cache_dir` | 任意。未設定 | YuEワーカーへ渡す任意のモデル／実行キャッシュディレクトリです。 |

固定revisionとpipeline設定を含むテンプレート全体は[`config.example.json`](../config.example.json)を参照してください。内部テスト専用の`engine`は設定可能なキーではありません。

## Cover、Motifと任意のパス

通常生成ではYuE用の`python`、`model`、`vae`を設定します。セットアップは`abc_tools`も候補として表示しますが、`null`の場合にアプリが自動検出できる構成もあります。

音源から採譜する場合は、`./setup.sh --stage cover`の出力にある`sheetsage_python`と`sheetsage_model`の値を設定します。SheetSage2のソース、モデル、venvはYuEとは分離し、公開用アプリの外に置いてください。ABCファイルを直接使うCoverではSheetSage2は不要です。Motifの音源区間切り出しには`/usr/bin/ffmpeg`にあるFFmpeg 6.1.xも必要です。詳しくは[INSTALL.ja.md](INSTALL.ja.md)を参照してください。

既存のJSONオブジェクトへ追加する値の例です（実際の絶対パスに置き換えてください）。

```json
{
  "python": "/path/to/YuE/venv/bin/python",
  "abc_tools": "/path/to/YuE/skills/yue2-music/scripts/abc_tools.py",
  "sheetsage_python": "/path/to/sheetsage-venv/bin/python",
  "sheetsage_model": "/path/to/SheetSage2-standalone"
}
```

これは設定全体ではなく、形式を示す断片です。必須の`model`、`vae`、`device`を含む既存設定を維持し、値だけを統合してください。

## LAN接続と安全性

既定の`host`はループバックのみです。信頼できるLAN内の別端末から接続する場合は、待受アドレスとリクエスト上の許可ホストをそれぞれ設定します。

```json
{
  "host": "0.0.0.0",
  "port": 7860,
  "allowed_hosts": ["127.0.0.1", "localhost", "[::1]", "192.168.1.20", "studio-pc"]
}
```

この例を既存ファイルへ統合し、IPアドレス／名前はブラウザURLで使う値に置き換えてください。WSLのポート転送を使う場合、転送先のアドレスとポートがアプリの実際の待受設定と一致する必要があります。`host`はサーバーが待ち受ける場所、`allowed_hosts`はHTTP Hostヘッダーの検査です。どちらも認証機能ではありません。本アプリにアカウント機能はないため、信頼できるプライベートネットワーク内だけで使用し、インターネットへ直接公開・転送しないでください。許可ホストにワイルドカードを使わないでください。

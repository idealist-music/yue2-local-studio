# ABC ↔ MIDI 往復編集

曲詳細の「MIDIを書き出す」から、保存済みABCの全曲、検出済みセクション、声部、または小節範囲をType 1 MIDIとして保存できます。ダウンロードされる往復セットZIPには `score.mid`、`source.abc`、`sidecar.json`、`README.txt` が入ります。VocalとInsは別トラックで、PPQは15360です。

DAWではVocal/Insのトラックを編集し、MIDIだけをアプリへ「MIDIを取り込む」からアップロードします。対象曲、譜面版、トラック、開始・終了小節を選び、解析結果と変更範囲を確認してから新しいABC版を保存します。保存後の音声生成は通常の譜面再生成操作から行います。

API利用時は `POST /api/midi/imports` に `application/octet-stream` でMIDIを送り、返されたIDへ任意で `POST /api/midi/imports/{id}/sidecar` を送ります。server exportのsidecarは元版ID、ABC SHA-256、snapshot SHA-256、PPQ、声部、範囲を照合します。DAW編集によるMIDI SHA-256の変更は差分警告として扱います。`preview` はトラック×チャンネルを明示してから実行し、`save` はpreview tokenと譜面HEADを再検証します。MIDI単体からは `.../{id}/new-song` でコードなし `cot=melody` の新規native ABCを作成できます。

画面では曲詳細から譜面版を選び、Vocal/Ins/両方、セクションまたは小節範囲、MIDI単体またはZIPを選択します。取り込み時は候補ごとにトラック番号、チャンネル、名前、音数、音域、重なりを確認し、各候補をVocal、Ins、無視へ割り当てます。複数候補を自動確定しません。sidecarを使う場合は個別に照合し、対象曲・版・範囲・ハッシュの警告を確認してから解析します。sidecarなしでは対象曲、版、開始・終了小節を手動確定します。

実DAWでの最短手順は、(1) 曲詳細の「MIDIを書き出す」で往復セットZIPを保存、(2) ZIP内の`score.mid`をDAWへ読み込む、(3) VocalまたはInsの音符を1つだけ変更、(4) WAVではなくMIDI（SMF Type 0/1、PPQ）として書き出す、(5) 画面の「MIDIを取り込む」で`.mid`を選び、必要ならZIP内の`sidecar.json`を個別に照合、(6) track×channelを割り当て、対象版・小節・移調・量子化を確認、(7) プレビューの音符差分を確認して「新しいABC版として保存」、(8) 「この版から再生成」の順です。WAVは音声試聴・音声書き出し用であり、MIDI往復編集の入力には使いません。

プレビューでは量子化の変更数・最大/合計ずれ、損失、変更小節、推定長、生成対象ABCを確認できます。「新しいABC版として保存」と「この版から再生成」は別操作です。再生成時は対象曲のStyle、Lyrics、Seedを初期値として使い、必要なら通常フォームで編集してから生成してください。対象曲にABCがない場合はCover採譜、またはMIDI単体から新規曲ABCを作成する導線を使用します。

対応するMIDIはSMF Type 0/1、PPQ分周です。Type 2、SMPTE、RMID、ポリフォニー、ドラムチャンネル、範囲外のノート、壊れたnote対は拒否します。velocity以外の演奏情報、CC、ペダル、ベンド、SysExはABCへ反映せず損失として表示します。ABCの有効な拍子・調・セクション位置はconductorトラックとsidecarへ記録し、選択区間の先頭へ状態を引き継ぎます。

MIDIの取り込みは対象範囲と同じ長さの部分置換です。対象外の譜面版は保持され、元曲や既存音声は上書きされません。ABCを外部編集した場合、公式YuE2 native ABC形式であることを確認してください。MIDI単体からの新曲作成とCover採譜は別の導線です。

問題がある場合は、保存された `data/midi/exports/` と `data/midi/imports/` を保全したままアプリを停止できます。追加されたMIDI版・操作記録は旧機能から無視され、通常生成、Cover、Motif、LAN設定は既存のまま使用できます。

復旧時はアプリを停止し、`data/backups/midi-schema-<UTC>.sqlite3` のSQLiteバックアップと`data/score_versions/`、`data/midi/`を別の場所へコピーします。既存ABCや音声は上書きされません。MIDI終端長と対象範囲長が一致しない場合、初期版は保存せず停止します。休符補完、時間倍率調整、切り詰めを選んで保存する機能はありません。

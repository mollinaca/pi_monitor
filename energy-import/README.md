# 電気・ガス履歴の更新

`pi-energy-import` は、私用の取得ExcelをPi上で次の正規化CSVへ変換します。これらのCSVと
Grafanaの静的ダッシュボードJSONは `data/` 配下にあり、個人の利用履歴を含むためGit管理外です。

| 出力ファイル | 列 | 用途 |
| --- | --- | --- |
| `data/energy/daily-electricity.csv` | `kind,date,usage,unit,status` | 日別電力 |
| `data/energy/monthly-usage.csv` | `kind,display_month,period_start,period_end,usage,unit,status` | 月別電気・ガス |
| `data/energy/billing.csv` | `kind,billing_month,period_start,period_end,usage,unit,charge_yen` | 請求明細 |
| `data/water/water-usage.csv` | `display_month,meter_reading_date,period_start,period_end,water_m3,sewer_m3,previous_water_m3,prior_year_water_m3,water_fee_yen,sewer_fee_yen,total_fee_yen` | 水道・下水道 |

入力はCSVではなく、3シートのExcel (`.xlsx`) とする。日付をExcelの日付セルとして保持でき、
月別・日別・請求明細を一つの取得物として検証できるためである。以下の依頼文をWindows版
ChatGPTデスクトップアプリで使い、ログインとワンタイムパスワードはブラウザの操作権を取って
自分で入力する。認証情報をチャットに書かない。

## Windows版ChatGPTへの依頼文

```text
ドコモでんき／ガスのマイページから、電気・ガスの使用履歴を更新して、
「電気ガス使用履歴.xlsx」というExcelファイルを作成してください。

ログインが必要な場面ではブラウザ操作を私に渡してください。ID、パスワード、ワンタイム
パスワードはチャットに表示・保存しないでください。ログイン後は、次の3シートをこの名前と
列順で作成してください。日付列は文字列ではなくExcelの日付セルにしてください。

1. シート名「月別使用量」
   列: 種別, 表示月, 使用開始日, 使用終了日, 使用量, 単位, 区分
   - 電気とガスを収録する。
   - 種別は「電気」または「ガス」、単位は電気が「kWh」、ガスが「m3」。
   - 区分は確定済みなら「表示実績」、当月途中なら「集計途中」、サイトに予測値があれば「予測」。
   - 表示月・開始日・終了日を省略しない。表示月はサイト上の月表示をそのまま記録する。
   - 集計途中と予測は表示実績へ合算しない（別行として残す）。

2. シート名「請求明細」
   列: 種別, 請求月, 使用開始日, 使用終了日, 使用量, 単位, 利用料金（税込円）
   - 電気・ガスを切り替えて、画面で選べる全請求月を取得する。
   - 請求月と使用期間を両方記録し、料金は税込円の数値だけを入れる。

3. シート名「日別使用量」
   列: 種別, 日付, 使用量, 単位, 区分
   - 電気の日別グラフで表示できる全日を取得する。
   - 種別は「電気」、単位は「kWh」。確定済みは「表示実績」、当月途中は「集計途中」。

各シートの先頭に、取得日・対象期間・出典URL・注意事項を記載して構いませんが、上記の列見出し
行より下にはデータ行だけを置いてください。SSID、アカウントID、パスワード、認証コードなどの
秘密情報はファイルへ含めないでください。
```

## Piへの反映

作成したExcelをPiへ安全にコピーしてから、Pi上で実行する。

```bash
cd /mnt/data/pi_monitor
uv run --project energy-import pi-energy-import /path/to/電気ガス使用履歴.xlsx
docker compose restart grafana
```

この操作はCSV、Grafana用の静的CSV Content、`energy-import.prom`を更新する。Excelは取込後にPiへ
残さない。`Energy Usage`ダッシュボードを再読み込みして表示を確認する。

水道CSVを同時に更新する場合は、`--water-csv /path/to/さいたま市水道_利用実績.csv` を追加する。
入力CSVはUTF-8で、列名 `表示月`、`検針日`、`使用期間`、`水道使用量_㎥`、`下水道使用量_㎥`、
`前回水道使用量_㎥`、`前年同期水道使用量_㎥`、`水道料金_円`、`下水道使用料_円`、`料金合計_円` を
必要とする。支払方法は保存しない。

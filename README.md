# pi_monitor

個人的な自宅環境のための監視・可視化プロジェクトです。Raspberry Pi (`192.168.100.201`) から、自宅LAN、Wi-Fi、インターネット接続、Pi本体、電気・ガス・水道の利用履歴を確認します。一般向けの製品や汎用テンプレートではなく、ネットワーク構成・認証情報・運用手順はこの環境を前提としています。

Pi上では外部ストレージの `/mnt/data/pi_monitor` に配置します。

## 作業引き継ぎ（AI・保守担当向け）

このREADMEを作業の起点とします。ローカルの作業場所は
`/mnt/d/workspace/dev/pi_monitor`、Pi側のリポジトリは
`/mnt/data/pi_monitor`です。ローカルのリポジトリ直下からPiへ接続するには、
次を実行します（親ディレクトリからなら鍵は`.ssh/codex-ai_SSHKEY`）。

```bash
ssh -i ../.ssh/codex-ai_SSHKEY root@192.168.100.201
```

| 対象 | 接続先・確認先 |
| --- | --- |
| Grafana | `http://192.168.100.201:3001/`。設定済みの管理者アカウントでログイン。LAN Mapは`/d/lan-map/lan-map`。 |
| Prometheus | Pi上の`http://127.0.0.1:9090/`。手元のブラウザからは後述のSSHポート転送を使う。 |
| Router | 管理IPは`192.168.100.1`。監視用の読み取り専用SSHアカウントとポートは`router-probe/config/probe.toml`を参照。 |
| AP | AP1は`https://192.168.100.246/`、AP2は`https://192.168.100.247/`。クラスタ仮想IPは`192.168.100.245`。監視には読み取り専用Webアカウントを使用。 |

Piへコードを反映する前にローカルの変更を確認し、通常のGit手順で同期します。
Piでは`cd /mnt/data/pi_monitor && git pull --ff-only`を使います。
Composeサービスの状態確認はPi側のリポジトリで`docker compose ps`、
ログ確認は`docker compose logs --tail=100 <service>`、必要な場合の起動は
`docker compose up -d`です。GrafanaのダッシュボードJSONは
`services/grafana/dashboards/`にあり、読み取り専用でマウントされます。
provisioningは約30秒ごとに更新を確認します。
GrafanaコンテナはUTCで動作しており、コンテナ内で実行されるSQLiteの
`datetime(..., 'localtime')` もUTCになります。JST表示が必要なテーブルでは、
SQL側で明示的に変換してください（Internet SpeedのMeasurement historyは`+9 hours`）。

ホストの定期収集は`pi-wifi-probe`、`pi-ap-web-probe`、`pi-router-probe`、
`pi-lan-map`、`pi-internet-speed-probe`、`pi-ssd-smart-probe`、
`pi-throttling-probe`のsystemd timer/serviceで管理します。Pi上での確認・手動実行は次の通りです。

```bash
systemctl list-timers --all 'pi-*.timer'
journalctl -u <name>.service -n 50 --no-pager
systemctl start <name>.service
```

プローブの設定は各`*-probe/config/`と`lan-map/config/`にあります。
systemd unitやtimerを変更した場合は、対応する`scripts/install-*.sh`をPiで実行して
再導入します。導入スクリプトは稼働中のtimerを再起動します。
Prometheusの収集間隔は`services/prometheus/prometheus.yml`、
textfileの鮮度アラートは`services/prometheus/textfile-freshness.rules.yml`で管理します。
Grafanaの`Probe Freshness`とPrometheusの`/alerts`で古いtextfileを確認できます。
通知先は未設定です。LAN Mapの入力・履歴・表示は`docs/lan-map-design.md`、
利用履歴の手動取込は`energy-import/README.md`を参照してください。

資格情報、SSID、BSSID、MAC、実端末名はREADME・Git・ログに記録しません。
Pi専用設定は`/mnt/data/pi_monitor/.config/`（ディレクトリ`0700`、秘密ファイル`0600`）に、
測定結果と履歴は`/mnt/data/pi_monitor/data/`に置きます。Routerのパスワードは
`.config/router_password.txt`、APのWeb認証情報は`.config/ap-web-probe.toml`、
端末名対応表もPiの`.config/`だけに置きます。

### 経過観察（2026-10-07時点）

1. **回線速度:** 以前の毎時00分側の実行でOokla CLI終了コード2の失敗が偏っていました。10月3日から毎時12分・42分に変更し、最初の21:42実行は成功しました。数日分の`pi-internet-speed-probe.service`のjournalで失敗頻度を比較してください。旧時刻18:00の失敗では`Error: [101] Network unreachable`を記録しましたが、原因は未確定です。失敗時は速度値を書かず、Grafanaは直近35分の成功値を表示するため、グラフの線だけで成否を判断しないでください。
2. **AP2 Web取得:** AP2ではブラウザログインやSelenium通信が不規則に失敗します。原因は未確定です。AP WebのjournalとLAN Mapの該当周期の`unavailable`表示を確認してください。接続端末0台が続く場合はAPページのレコード形式変更も調べてください。
3. **次の利用履歴取込:** 取込途中の失敗で一部CSVだけが更新され、前回の成功メトリクスが残る可能性があります。次回の手動取込では終了コード、CSV、Grafanaダッシュボード、`energy-import.prom`の更新時刻を確認してください。

## 実装技術

- Docker Compose: Gatus、Prometheus、node_exporter、Grafanaを運用
- Python 3.11 / `uv`: Wi-Fi、ルーター、SSD SMART、回線速度のホスト側プローブと、利用履歴のCSV変換
- systemd timer: 負荷のある測定やハードウェア取得を定期実行
- Prometheus / Grafana: 監視メトリクスの収集・可視化
- Grafana TestData CSV Content: 電気・ガス・水道の手入力履歴を、DBや追加プラグインなしで可視化

## ディレクトリ構造

```text
pi_monitor/
├── compose.yaml                  # コンテナ構成
├── services/                     # Gatus、Prometheus、Grafanaの設定とダッシュボード
├── *-probe/                      # Piホストで動くPythonプローブ（systemd管理）
├── energy-import/                # 電気・ガス・水道のCSV／Grafanaデータ生成
├── scripts/                      # 初期設定・systemd導入補助
└── data/                         # 実行時データ。外部ストレージ上で保持しGit管理外
```

## ポイント

- 監視コンテナと、NetworkManagerやSMARTを操作するホスト側プローブを分離しています。
- 秘密情報と個人利用データはGitに入れません。Pi専用の認証情報・端末名対応表は `/mnt/data/pi_monitor/.config/`（ディレクトリ0700、秘密ファイル0600、Gitでは中身を除外）に置きます。`data/`、Grafana DB、プロバイダーから取得した元ファイルも実行環境だけに置きます。
- Piへの反映は `git pull --ff-only` を基本とし、永続データは `/mnt/data/pi_monitor/data/` に集約します。
- 利用履歴はライブテレメトリではなく手動更新です。インポート成否など最小限の状態だけをnode_exporter textfileで公開します。

## 構成方針

- Gatus: LANとインターネットのヘルスダッシュボード
- Wi-Fi probe: AP・周波数帯ごとの無線品質をホスト上で測定
- node_exporter: Wi-Fi probeの測定値とホストメトリクスを公開
- Prometheus: GatusとPiのnode_exporterをジョブごとの間隔で収集し、時系列データを保存
- Grafana: Prometheusのデータを可視化

Gatus、Wi-Fi probe、node_exporter、Prometheus、Grafanaを実装済みです。Prometheusはnode_exporterとGatusを収集します。

定期プローブとLAN Mapは、必要なデータの取得・解釈・保存まで完了した場合に終了コード`0`、取得不能・解釈不能・保存失敗の場合に`1`を返します。値として測定できたパケット損失やSMARTの健康状態不良は、それ自体ではスクリプトの異常終了ではありません。失敗理由は標準エラーへ簡潔に出力し、systemdサービスのjournalで確認します。専用のログファイルは作成しません。systemdによる強制停止など、スクリプトが出力できない失敗はjournalのサービス状態を確認します。

## 電気・ガス使用履歴

電気・ガスの履歴は私用データのためGitへ入れません。プロバイダー画面から取得した
ExcelをPiへコピーし、次を実行します。正規化CSVは`data/energy/`へ保存され、Grafanaの
`Energy Usage`ダッシュボード用の静的CSV Contentも同時に生成されます。Grafana標準の
TestDataデータソースを使うため、追加プラグインやDBは不要です。

```bash
cd /mnt/data/pi_monitor
uv run --project energy-import pi-energy-import /path/to/電気ガス使用履歴.xlsx \
  --data-directory data/energy \
  --dashboard services/grafana/dashboards/energy/energy-usage.json \
  --metrics data/node-exporter/textfile/energy-import.prom
```

このコマンドは、日別電力・月別電力／ガス・請求明細のCSVを生成します。Grafanaへ埋め込む
表示データも再生成するため、ダッシュボードJSONはGit管理外です。textfileに出すのは取込の
成否、最終取込時刻、行数のみであり、履歴値自体はPrometheusへ保存しません。

## ディレクトリ

```text
pi_monitor/
├── compose.yaml
├── services/
│   ├── gatus/
│   │   └── config.yaml
│   ├── prometheus/
│   │   └── prometheus.yml
│   └── grafana/
│       ├── dashboards/
│       │   ├── devices/          # Pi、Router、AP、プローブの状態
│       │   ├── network/          # 到達性、Wi-Fi品質、速度、LAN Map
│       │   └── energy/           # 手動インポートが生成する利用履歴
│       └── provisioning/
├── ssd-smart-probe/            # ホスト側、日次の外部SSD SMARTプローブ
├── wifi-probe/                 # ホスト側Pythonプロジェクト
└── data/                       # 実行時データ。Git管理外
    ├── gatus/
    ├── prometheus/
    ├── grafana/
    └── node-exporter/
        └── textfile/
```

コンテナ定義はリポジトリ直下の `compose.yaml` に集約し、各サービス固有の設定を `services/` 以下に置きます。NetworkManagerと無線デバイスを操作するWi-Fi probeだけは、Dockerではなくホスト上のsystemdから実行します。

## Gatusの監視対象

LAN内は30秒間隔、インターネット上の対象は5分間隔で監視します。

- ルーター (`192.168.100.1`) へのICMP到達性
- AP-1F (`192.168.100.246`) へのICMP到達性
- AP-2F (`192.168.100.247`) へのICMP到達性
- 外部IP (`1.1.1.1`) へのICMP到達性
- Cloudflare DNS (`1.1.1.1`) による名前解決
- Yahoo Japan、Google、GitHub、X、DiscordへのHTTPS到達性
- 米国西岸・東岸、欧州中央・北部、東南アジアへのHTTPS到達性

地域別監視ではHetznerの地域別テストホストへRangeリクエストを送り、100MBファイル全体ではなく1バイトだけを取得します。

Gatusの履歴は、外部ストレージ上の `/mnt/data/pi_monitor/data/gatus/gatus.db` に保存します。

## インターネット回線速度

Ookla Speedtest CLIをPiホスト上で実行し、その都度自動選択された測定サーバーに対する下り・上り速度、idle latency、jitter、試験通信量、成否を収集します。Piの通常経路である有線`eth0`へ明示的にバインドするため、これは有線LAN地点から見たインターネット接続性能です。Wi-Fi区間の実効速度を表すものではありません。成功した測定は時刻・上下速度・実際のサーバーID／名前／ロケーションを`data/internet-speed/history.db`へ1回1行で保存し、Grafanaの`Internet Speed`に履歴テーブルを表示します。測定サーバーが変わった前後の速度は条件が異なるため注意して比較してください。

速度試験は帯域と通信量を大きく使うため、Prometheusのscrapeでは実行しません。`pi-internet-speed-probe.timer` が毎時12分・42分に実行し、結果を `data/node-exporter/textfile/internet-speed.prom` へ出力します。Prometheusの`internet-speed`ジョブは3分ごとに既存のTextfileを読むだけです。

導入後は手動実行で結果を確認してからtimerを有効化します。

```bash
sudo ./scripts/install-internet-speed-probe.sh
sudo systemctl start pi-internet-speed-probe.service
journalctl -u pi-internet-speed-probe.service -n 50 --no-pager
sudo systemctl enable --now pi-internet-speed-probe.timer
```

## Raspberry Piへの配置

```bash
cd /mnt/data
git clone git@github.com:mollinaca/pi_monitor.git
cd pi_monitor
```

既にclone済みの場合は更新します。

```bash
cd /mnt/data/pi_monitor
git pull
```

Prometheusを初めて起動する前に、外部ストレージのデータディレクトリを準備します。
スクリプトはComposeで固定している公式イメージから実行UID/GIDを取得し、
`/mnt/data/pi_monitor/data/prometheus` だけに所有者と権限を設定します。

```bash
cd /mnt/data/pi_monitor
sudo ./scripts/prepare-container-storage.sh
```

Grafanaの管理者パスワードは、Grafanaの永続DB
`/mnt/data/pi_monitor/data/grafana` 内で管理します。外部のパスワードファイルは使用しません。
新しいGrafana DBで初回起動した場合は、初回ログイン後すぐに管理者パスワードを変更してください。

## 起動と停止

```bash
cd /mnt/data/pi_monitor
docker compose up -d
docker compose down
```

Gatusだけを操作する場合:

```bash
docker compose restart gatus
docker compose logs --tail=100 gatus
```

node_exporterだけを操作する場合:

```bash
docker compose restart node-exporter
docker compose logs --tail=100 node-exporter
curl http://127.0.0.1:9100/metrics
```

起動後は、LAN内のブラウザから以下へアクセスできます。

```text
http://192.168.100.201:8080/
http://192.168.100.201:3001/
```

node_exporterはPiのホストネットワークで動作し、Dockerブリッジのゲートウェイ
`172.17.0.1:9100`で待ち受けます。Wi-Fi probeなどが生成した
`data/node-exporter/textfile/*.prom` とPiのCPU、メモリ、ディスク、ネットワークなどの
ホスト指標を公開し、Prometheusは`host.docker.internal:9100`から収集します。

### 電圧低下・性能制限

Pi上の`pi-throttling-probe.timer`が1分ごとに`vcgencmd get_throttled`を実行し、
`data/node-exporter/textfile/pi-throttling.prom`へ出力します。導入はPiで
`scripts/install-throttling-probe.sh`を実行します。初回はサービスの終了状態と
`journalctl -u pi-throttling-probe.service -n 50 --no-pager`を確認します。
`Raspberry Pi Hardware`には「現在」と「起動後に一度でも発生」の2つのグラフがあります。
後者はファームウェアの履歴ビットを表示するため、状態が解消しても再起動まで1のままです。
1分未満の一時的な事象は現在のグラフには残らない場合があります。

### 定期プローブのtextfile鮮度

node_exporterの`node_textfile_mtime_seconds`を使い、定期プローブがtextfileを更新しなくなった場合を検出します。
`ap-web.prom`、`router.prom`、`internet-speed.prom`、`lan-map.prom`、4つの`wifi-*.prom`は
最終更新から24時間、日次の`ssd-smart.prom`は実行時刻のずれを見込んで30時間、
毎分の`pi-throttling.prom`は10分を超えると、それぞれの鮮度アラートが発火します。
手動実行の`energy-import.prom`は対象外です。

結果はGrafanaの`Device Monitoring`フォルダーにある`Probe Freshness`ダッシュボードと、
Pi上のPrometheusの`/alerts`で確認できます。現在は通知先を設定していないため、
アラートが発火してもメールや端末への通知は届きません。これは既存ファイルの更新停止を
検出する設定です。ファイルが削除された場合や一度も生成されていない場合は検出しません。
ダッシュボードには、各ファイルの最終更新時刻と、対応するPrometheusジョブが最後に
そのファイルの指標を収集した時刻を同じ行に表示します。ジョブによって収集間隔は異なります。
最終スクレイプ時刻が進んでいるのにファイルの時刻が古い場合、対応するプローブや
timerのjournalを確認してください。

今後、定期プローブ・監視対象・textfileを追加または改名する場合は、
`services/prometheus/textfile-freshness.rules.yml`の対象ファイルと期限、
`services/grafana/dashboards/devices/probe-freshness.json`の表示対象と期限も合わせて更新してください。
手動実行のデータは、更新期限を定めて監視する必要がある場合にのみ追加します。

Prometheusのポート9090もPi自身のlocalhostだけに公開します。SSHポートフォワードで
一時的にUIを確認する場合は、作業端末で次を実行します。

```bash
ssh -i ../.ssh/codex-ai_SSHKEY -L 9090:127.0.0.1:9090 root@192.168.100.201
```

その後、作業端末のブラウザで `http://127.0.0.1:9090/targets` を開きます。

GrafanaはLAN向けにポート3001で公開します。Prometheusをコード管理されたデータソースとして登録し、
Wi-Fi品質、Gatus Health、Pi Hardwareのダッシュボードを提供します。ログインには、GrafanaのDBに設定済みの管理者認証情報を使用します。

Grafanaのダッシュボードは用途別に3フォルダーへ配置します。

| フォルダー | ダッシュボード |
| --- | --- |
| Energy Usage | Energy Usage（手動インポートで生成） |
| Device Monitoring | Raspberry Pi Hardware、Router Health、AP Health、Probe Freshness |
| Network Monitoring | Gatus Health、Wi-Fi Quality、Internet Speed、LAN Map |

新しいダッシュボードを追加する場合は、監視対象の機器・収集処理か、通信・接続状態かで配置先を選びます。
Energy Usageの生成先`services/grafana/dashboards/energy/`は、手動インポートの出力先と共通です。

## Pi本体とストレージの監視

PiのCPU使用率、load、メモリ使用率、CPU温度、root filesystemと外部SSDの使用率、microSDのI/O量・I/O圧力は、node_exporterの標準メトリクスで収集します。`raspberry-pi`ジョブの収集間隔は1分です。これはカーネルカウンタを読み取るだけで、収集自体はmicroSDへ書き込みません。

Grafanaの`Device Monitoring`フォルダにある`Raspberry Pi Hardware`ダッシュボードで確認できます。

microSDカードには、一般に残寿命や残書込み回数を示す標準的な取得方法がありません。このため、容量、書込み量、I/O待ち、I/O利用率を早期警戒のためのトレンドとして監視します。

外部SSDのSMARTは、ホスト上の`ssd-smart-probe`が毎日03:17に読み取り専用で収集します。プローブはSMART自己テストを開始せず、結果を`data/node-exporter/textfile/ssd-smart.prom`へ出力します。PrometheusはSMARTメトリクスだけを専用の1時間ジョブで読み込みますが、これは既に生成されたTextfileを読むだけであり、SMARTコマンドの実行頻度は日次のままです。手動試験の結果は次回scrape時にGrafanaへ反映されます。

初回導入後は、timerを有効化する前に手動で結果を確認します。

```bash
cd /mnt/data/pi_monitor
sudo ./scripts/install-ssd-smart-probe.sh
sudo systemctl start pi-ssd-smart-probe.service
journalctl -u pi-ssd-smart-probe.service -n 50 --no-pager
curl -fsS http://127.0.0.1:9100/metrics | grep '^home_ssd_smart_'
sudo systemctl enable --now pi-ssd-smart-probe.timer
```

SMARTの健康状態や残予備領域は故障時期を保証せず、残寿命の予測でもありません。USB接続、電源、コントローラ、物理的な故障などにより、SMARTが正常でも突然故障することがあります。重要なデータは監視とは別にバックアップしてください。実機の`Total_LBAs_Written`は単位が確認できないため、生値のトレンドとしてのみ表示し、TB/TBWや残寿命に換算しません。

## データ保存

実行時データはすべて外部ストレージ上の `/mnt/data/pi_monitor/data` 以下へ保存し、Gitでは管理しません。Dockerコンテナのログは `local` ドライバーで1ファイル10MB、最大3ファイルに制限しています。

Prometheusの時系列データは `/mnt/data/pi_monitor/data/prometheus` に保存し、2年または10GBのうち先に到達した上限で古いデータを削除します。
Grafanaの設定DBは `/mnt/data/pi_monitor/data/grafana` に保存します。

Dockerイメージ自体は、現在のホスト共通設定に従って `/var/lib/docker` に保存されます。この保存先の変更は既存コンテナ全体に影響するため、本プロジェクトでは扱いません。

## セキュリティ上の前提

GatusのWeb UIは認証なしでポート8080に公開します。GrafanaのWeb UIはポート3001で認証付き公開です。ルーター側でポート転送せず、信頼できるLAN内だけから利用してください。node_exporterのポート9100とPrometheusのポート9090はLANへ公開しません。

SSID、BSSID、Wi-Fiパスワードなどの無線識別情報と認証情報はGitへ保存しません。Wi-Fi接続情報はPi上のNetworkManagerプロファイルで管理します。

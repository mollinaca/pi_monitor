# Home Network Monitor

Raspberry Pi (`192.168.100.201`) から、自宅LAN、Wi-Fi、インターネットの状態を監視するプロジェクトです。Raspberry Pi上では、外部ストレージ上の `/mnt/data/pi_monitor` に配置することを前提とします。

## 構成方針

- Gatus: LANとインターネットのヘルスダッシュボード
- Wi-Fi probe: AP・周波数帯ごとの無線品質をホスト上で測定
- node_exporter: Wi-Fi probeの測定値とホストメトリクスを公開
- Prometheus: Gatusを30秒ごと、Piのnode_exporterを1分ごとに収集し、時系列データを保存
- Grafana: Prometheusのデータを可視化

Gatus、Wi-Fi probe、node_exporter、Prometheus、Grafanaを実装済みです。Prometheusはnode_exporterとGatusを収集します。

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
│       │   ├── gatus/gatus-health.json
│       │   ├── hardware/pi-hardware.json
│       │   └── wifi/wifi-quality.json
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

Ookla Speedtest CLIをPiホスト上で実行し、固定した東京の測定サーバー（ID `48463`）に対する下り・上り速度、idle latency、jitter、試験通信量、成否を収集します。Piの通常経路である有線`eth0`へ明示的にバインドするため、これは有線LAN地点から見たインターネット接続性能です。Wi-Fi区間の実効速度を表すものではありません。

速度試験は帯域と通信量を大きく使うため、Prometheusのscrapeでは実行しません。`pi-internet-speed-probe.timer` が毎時00分・30分に実行し、結果を `data/node-exporter/textfile/internet-speed.prom` へ出力します。Prometheusの`internet-speed`ジョブは1分ごとに既存のTextfileを読むだけです。

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

node_exporterのポート9100はPi自身のlocalhostだけに公開します。Wi-Fi probeが生成した
`data/node-exporter/textfile/*.prom` とPiのCPU、メモリ、ディスクなどのホスト指標を公開し、
PrometheusからはCompose内部ネットワーク経由で収集します。

Prometheusのポート9090もPi自身のlocalhostだけに公開します。SSHポートフォワードで
一時的にUIを確認する場合は、作業端末で次を実行します。

```bash
ssh -i ../.ssh/codex-ai_SSHKEY -L 9090:127.0.0.1:9090 root@192.168.100.201
```

その後、作業端末のブラウザで `http://127.0.0.1:9090/targets` を開きます。

GrafanaはLAN向けにポート3001で公開します。Prometheusをコード管理されたデータソースとして登録し、
Wi-Fi品質、Gatus Health、Pi Hardwareのダッシュボードを提供します。ログインには、GrafanaのDBに設定済みの管理者認証情報を使用します。

## Pi本体とストレージの監視

PiのCPU使用率、load、メモリ使用率、CPU温度、root filesystemと外部SSDの使用率、microSDのI/O量・I/O圧力は、node_exporterの標準メトリクスで収集します。`raspberry-pi`ジョブの収集間隔は1分です。これはカーネルカウンタを読み取るだけで、収集自体はmicroSDへ書き込みません。

Grafanaの`Pi Hardware`フォルダにある`Raspberry Pi Hardware`ダッシュボードで確認できます。

microSDカードには、一般に残寿命や残書込み回数を示す標準的な取得方法がありません。このため、容量、書込み量、I/O待ち、I/O利用率を早期警戒のためのトレンドとして監視します。

外部SSDのSMARTは、ホスト上の`ssd-smart-probe`が毎日03:17に読み取り専用で収集します。プローブはSMART自己テストを開始せず、結果を`data/node-exporter/textfile/ssd-smart.prom`へ出力します。PrometheusはSMARTメトリクスだけを専用の5分ジョブで読み込みますが、これは既に生成されたTextfileを読むだけであり、SMARTコマンドの実行頻度は日次のままです。手動試験の結果もGrafanaへ速やかに反映できます。

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

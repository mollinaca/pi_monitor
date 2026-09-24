# Home Network Monitor

Raspberry Pi (`192.168.100.201`) から、自宅LAN、Wi-Fi、インターネットの状態を監視するプロジェクトです。Raspberry Pi上では、外部ストレージ上の `/mnt/data/pi_monitor` に配置することを前提とします。

## 構成方針

- Gatus: LANとインターネットのヘルスダッシュボード
- Wi-Fi probe: AP・周波数帯ごとの無線品質をホスト上で測定
- node_exporter: Wi-Fi probeの測定値とホストメトリクスを公開
- Prometheus: node_exporterを30秒ごとに収集し、時系列データを保存
- Grafana: Prometheusのデータを可視化

Gatus、Wi-Fi probe、node_exporter、Prometheus、Grafanaを実装済みです。

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
│       └── provisioning/
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
- Yahoo JapanとGoogleへのHTTPS到達性
- 米国西岸・東岸、欧州中央・北部、東南アジアへのHTTPS到達性

地域別監視ではHetznerの地域別テストホストへRangeリクエストを送り、100MBファイル全体ではなく1バイトだけを取得します。

Gatusの履歴は、外部ストレージ上の `/mnt/data/pi_monitor/data/gatus/gatus.db` に保存します。

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

Grafanaも同じスクリプトで準備します。初回だけ、Pi上のroot専用ディレクトリ
`/root/.config/pi_monitor/grafana_admin_password` にランダムな管理者パスワードを生成します。
このファイルはGit管理せず、表示も出力もしません。

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
Wi-Fi品質ダッシュボードを初期表示します。ログインにはユーザー名`admin`と、Piの
`/root/.config/pi_monitor/grafana_admin_password` に保管したパスワードを使用します。

## データ保存

実行時データはすべて外部ストレージ上の `/mnt/data/pi_monitor/data` 以下へ保存し、Gitでは管理しません。Dockerコンテナのログは `local` ドライバーで1ファイル10MB、最大3ファイルに制限しています。

Prometheusの時系列データは `/mnt/data/pi_monitor/data/prometheus` に保存し、2年または10GBのうち先に到達した上限で古いデータを削除します。
Grafanaの設定DBは `/mnt/data/pi_monitor/data/grafana` に保存します。

Dockerイメージ自体は、現在のホスト共通設定に従って `/var/lib/docker` に保存されます。この保存先の変更は既存コンテナ全体に影響するため、本プロジェクトでは扱いません。

## セキュリティ上の前提

GatusのWeb UIは認証なしでポート8080に公開します。GrafanaのWeb UIはポート3001で認証付き公開です。ルーター側でポート転送せず、信頼できるLAN内だけから利用してください。node_exporterのポート9100とPrometheusのポート9090はLANへ公開しません。

SSID、BSSID、Wi-Fiパスワードなどの無線識別情報と認証情報はGitへ保存しません。Wi-Fi接続情報はPi上のNetworkManagerプロファイルで管理します。

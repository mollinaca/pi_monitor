# Home Network Monitor

Raspberry Pi (`192.168.100.201`) から、自宅LAN、Wi-Fi、インターネットの状態を監視するプロジェクトです。Raspberry Pi上では、外部ストレージ上の `/mnt/data/pi_monitor` に配置することを前提とします。

## 構成方針

- Gatus: LANとインターネットのヘルスダッシュボード
- Wi-Fi probe: AP・周波数帯ごとの無線品質をホスト上で測定
- node_exporter: Wi-Fi probeの測定値とホストメトリクスを公開
- Prometheus: 時系列データを保存
- Grafana: Prometheusのデータを可視化

現在はGatusのみ実装済みです。Wi-Fi probe、node_exporter、Prometheus、Grafanaは順次追加します。

## ディレクトリ

```text
pi_monitor/
├── compose.yaml
├── services/
│   ├── gatus/
│   │   └── config.yaml
│   ├── prometheus/             # 今後追加
│   └── grafana/                # 今後追加
├── wifi-probe/                 # 今後追加するホスト側Pythonプロジェクト
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

起動後は、LAN内のブラウザから以下へアクセスできます。

```text
http://192.168.100.201:8080/
```

## データ保存

実行時データはすべて外部ストレージ上の `/mnt/data/pi_monitor/data` 以下へ保存し、Gitでは管理しません。Dockerコンテナのログは `local` ドライバーで1ファイル10MB、最大3ファイルに制限しています。

Dockerイメージ自体は、現在のホスト共通設定に従って `/var/lib/docker` に保存されます。この保存先の変更は既存コンテナ全体に影響するため、本プロジェクトでは扱いません。

## セキュリティ上の前提

GatusのWeb UIは認証なしでポート8080に公開します。ルーター側でポート転送せず、信頼できるLAN内だけから利用してください。

SSID、BSSID、Wi-Fiパスワードなどの無線識別情報と認証情報はGitへ保存しません。Wi-Fi接続情報はPi上のNetworkManagerプロファイルで管理します。

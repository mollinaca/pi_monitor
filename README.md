# Home Network Monitor

Raspberry Pi (`192.168.100.201`) から、自宅LANとインターネットへの到達性を監視するプロジェクトです。Raspberry Pi上では、外部ストレージ上の `/mnt/data/pi_monitor` に配置することを前提とします。

## 採用ツール

[Gatus](https://github.com/TwiN/gatus) を使用します。監視対象と判定条件をYAMLで管理でき、単一のDockerコンテナでWeb UI、履歴、ICMP/DNS/HTTP/TCP監視、Prometheus形式のメトリクスを提供します。

現時点では、次の項目を監視します。

- ルーター (`192.168.100.1`) へのICMP到達性
- 1FのCisco WAP150 (`192.168.100.246`) へのICMP到達性
- 2FのCisco WAP150 (`192.168.100.247`) へのICMP到達性
- 外部IP (`1.1.1.1`) へのICMP到達性
- Cloudflare DNS (`1.1.1.1`) による名前解決
- `https://example.com/` へのHTTPS到達性
- Yahoo JapanとGoogleへのHTTPS到達性
- 米国西岸（Hillsboro）・米国東岸（Ashburn）へのHTTPS到達性
- 欧州中央（Falkenstein）・欧州北部（Helsinki）へのHTTPS到達性
- 東南アジア（Singapore）へのHTTPS到達性

LAN内のルーターは30秒間隔、インターネット上の対象は5分間隔で監視します。地域別監視ではHetznerの地域別テストホストへRangeリクエストを送り、100MBファイル全体ではなく1バイトだけを取得します。

監視履歴は外部ストレージ上の `/mnt/data/pi_monitor/data/gatus.db` に保存されます。実行時データはGit管理しません。

## Raspberry Pi上の配置

このリポジトリをRaspberry Piの次の場所へ配置します。

```text
/mnt/data/pi_monitor
```

起動操作も同じディレクトリで行います。

```bash
cd /mnt/data/pi_monitor
docker compose up -d
```

Compose設定では、GatusのSQLiteデータを絶対パス `/mnt/data/pi_monitor/data` に保存します。コンテナを削除・再作成しても、このディレクトリを削除しない限り履歴は維持されます。

## 起動と停止

```bash
docker compose up -d
docker compose down
```

起動後、LAN内のブラウザから次のURLを開きます。

```text
http://192.168.100.201:8080/
```

設定を変更した場合は、コンテナを再起動します。

```bash
docker compose restart gatus
```

ログと状態の確認:

```bash
docker compose ps
docker compose logs --tail=100 gatus
```

## 構成

- `compose.yaml`: コンテナ定義。公式ARM64対応イメージをバージョン固定して使用
- `config/config.yaml`: 監視対象と判定条件
- `/mnt/data/pi_monitor/data/`: SQLiteデータベース（外部ストレージ、Git管理外）
- `pi_monitor.sh`: 既存のRaspberry Pi本体情報収集スクリプト（現時点ではGatusと未統合）

DockerのコンテナログはSDカードの消費と書き込みを抑えるため、`local`ドライバーで1ファイル10MB、最大3ファイルに制限しています。

Dockerイメージ自体は、現在のホスト共通設定に従って `/var/lib/docker` に保存されます。この保存先を外部ストレージへ変更すると既存の全コンテナに影響するため、本プロジェクトでは変更しません。必要であれば、Docker全体の移行作業として別途実施します。

## セキュリティ上の前提

Web UIは認証なしでポート8080に公開されます。ルーター側でポート転送せず、信頼できるLAN内だけから利用してください。インターネット公開する場合は、認証とTLSを追加します。

ICMP監視に必要な権限だけを与えるため、コンテナには `NET_RAW` capabilityを追加しています。ホストネットワークや特権モードは使用しません。

## 今後の候補

- LAN内デバイスの追加
- 通知先の設定
- インターネット回線速度の定期測定
- Wi-Fi専用測定経路の追加
- Prometheus/Grafanaへの拡張

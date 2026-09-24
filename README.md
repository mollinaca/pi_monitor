# Home Network Monitor

Raspberry Pi (`192.168.100.201`) から、自宅LANとインターネットへの到達性を監視するプロジェクトです。

## 採用ツール

[Gatus](https://github.com/TwiN/gatus) を使用します。監視対象と判定条件をYAMLで管理でき、単一のDockerコンテナでWeb UI、履歴、ICMP/DNS/HTTP/TCP監視、Prometheus形式のメトリクスを提供します。

現時点では、次の4項目を監視します。

- ルーター (`192.168.100.1`) へのICMP到達性
- 外部IP (`1.1.1.1`) へのICMP到達性
- Cloudflare DNS (`1.1.1.1`) による名前解決
- `https://example.com/` へのHTTPS到達性

監視履歴は `data/gatus.db` に保存されます。実行時データはGit管理しません。

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
- `data/`: SQLiteデータベース（Git管理外）
- `pi_monitor.sh`: 既存のRaspberry Pi本体情報収集スクリプト（現時点ではGatusと未統合）

## セキュリティ上の前提

Web UIは認証なしでポート8080に公開されます。ルーター側でポート転送せず、信頼できるLAN内だけから利用してください。インターネット公開する場合は、認証とTLSを追加します。

ICMP監視に必要な権限だけを与えるため、コンテナには `NET_RAW` capabilityを追加しています。ホストネットワークや特権モードは使用しません。

## 今後の候補

- LAN内デバイスの追加
- 通知先の設定
- インターネット回線速度の定期測定
- Wi-Fi専用測定経路の追加
- Prometheus/Grafanaへの拡張

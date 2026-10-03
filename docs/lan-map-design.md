# LANマップの実装と運用

状態: Raspberry Piへ反映済み。Grafanaの`Network Monitoring`フォルダーで`LAN Map`を表示している。SQLiteデータソースプラグインは`frser-sqlite-datasource@4.0.6`に固定する。

## 表示の意味

- 5分ごとのスナップショットから、Router → ポート → AP／端末、およびAP → Wi-Fi端末を表示する。
- RouterのスイッチMAC表から分かるのは「そのポートの先にMACが見える」ことまでで、端末がRouterへ直接有線接続されている証明ではない。Piの`eth0`だけはMACを照合して有線端末と識別する。
- RouterのDHCPリースやARPキャッシュだけで接続線を作らない。IPは補足情報として表示する。
- 過去の状態は当時の名称、MAC、接続関係を保存したスナップショットから表示する。現在の端末名を過去へ再適用しない。

## 入力と収集時刻

| 入力 | 保存先・用途 |
| --- | --- |
| AP Web probe | APごとの接続端末一覧と収集時刻を`data/ap-web-probe/ap1.json`、`ap2.json`へ保存。PrometheusにはAP・帯域ごとの集計値だけを出し、端末別のMACや名前をラベルとして出さない。 |
| Router probe | DHCP、ARP、スイッチMAC表の応答と収集時刻を`data/router-probe/latest.json`へ保存。Prometheusには利用率、カウンタ、表の件数などを出す。 |
| `device-names.toml` | Piの`/mnt/data/pi_monitor/.config/`に置くroot専用のMAC→表示名対応表。Git管理外。 |
| Pi自身 | `/sys/class/net/eth0/address`と`/sys/class/net/wlan0/address`からMACを読む。 |

AP WebとRouterのtimerは5分周期の開始時刻と、その約30秒後に起動する。`pi-lan-map.timer`は同じ周期の3分30秒後に起動する。LAN Mapはその5分周期内に収集された入力だけを使う。APまたはRouterの入力が欠けた周期も、該当sourceを`unavailable`としてDBに残し、サービスは終了コード1を返す。前周期の接続一覧を現在のものとして流用しない。

## 突合と表示名

1. MACを小文字のコロン区切りとして検証する。AP接続一覧にあるMACは`AP → Wi-Fi端末`として表示し、Routerポート上の端末として重複表示しない。複数APから同じMACが得られた場合は、収集時刻が新しい方を採る。
2. Routerのスイッチ表にだけあるMACは`Routerポート → 端末`として表示する。Piの`eth0` MACは`wired`、それ以外は`port_learned`とする。Piの`wlan0` MACはRouterポート上の端末から除き、その周期のAP接続一覧にある場合だけAPへ結ぶ。
3. APは設定済みのRouterポートへ結ぶ。現在の設定はAP1がポート2、AP2がポート5。AP管理MACは、その周期のRouter ARP表で管理IPに一致した場合にスイッチ表の端末一覧から除く。ARPから消えた周期には重複表示の可能性がある。
4. 表示名は手動の`device-names.toml`、APが返すホスト名、MAC一致のRouter DHCP名、MACの順で選ぶ。APが返す`unknown`は使わない。Pi自身には専用の表示名を使う。異なるMACを一つの端末として自動統合しない。

ノードIDは`router`、`apap1`、`apap2`、`mac<12桁の16進数>`など表示名と独立した値とする。線にはAP接続、スイッチ表、設定済みAPポートなどの根拠を保存する。

## SQLite履歴

`data/lan-map/history.db`に専用SQLite DBを置く。Python標準ライブラリの`sqlite3`を使い、常駐SQLiteサービスはない。保持期間は730日。実運用で730日分の保持結果はまだ検証されていない。

| テーブル | 内容 |
| --- | --- |
| `snapshot` | 5分周期の`cycle_at`と保存時刻。周期は一意で、同周期の再実行は置き換える。 |
| `source` | Router/APごとの観測時刻と`observed`／`unavailable`。 |
| `node` | その周期の機器・端末・ポートの表示名、MAC、IP、帯域、状態。 |
| `edge` | その周期の線の両端、根拠、帯域。 |

4テーブルの更新と保持期限切れの削除は同じトランザクションで行う。SQLiteはロールバックジャーナルを使い、DBはGrafanaコンテナへ読み取り専用でマウントする。バックアップを取る場合はSQLiteのバックアップAPIなど整合性を保てる方法を使う。

## Grafana表示と時刻指定

Grafanaの時間範囲の**終了時刻T**に対して、`cycle_at <= T`の最新スナップショットを選ぶ。画面には選ばれた周期、Tからの経過時間、Router/AP別の観測状態と時刻、Node graph、端末一覧を表示する。経過時間が5分以上なら赤で示す。Node graphはForce自動配置で、座標は固定しない。

選択は5分周期の`cycle_at`単位であり、Tが周期途中ならTより後に取得された同周期の入力を含む場合がある。`Source observations`の時刻はSQLiteの`datetime(observed_at, 'unixepoch', 'localtime')`で文字列として表示している。これらの表示粒度と時刻表現は現状の運用で許容している。

## 運用と機密情報

LAN Mapは`home_lan_map_timestamp_seconds`、ノード数、Router/AP別入力の鮮度だけをPrometheusへ出す。端末のMAC、IP、名前はPrometheusへ出さない。`lan-map.prom`の更新停止はtextfile鮮度監視の対象で、24時間を超えるとアラートになる。収集失敗の詳細はsystemd journalで確認する。

SSID、BSSID、パスワード、実MAC、実端末名、スナップショット、履歴DBはGitやテストログへ載せない。テストは匿名化したfixtureを使う。Grafanaは認証付きでLAN内へ公開し、ダッシュボードとSQLiteデータソースはprovisioningで管理する。

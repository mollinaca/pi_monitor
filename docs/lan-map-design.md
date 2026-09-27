# LANマップ設計案

状態: 実装中。Grafana SQLiteプラグイン4.0.6は導入済み。マップ本体はローカルでテスト済み、Piへの反映前。

## 目的と表示の意味

- 5分ごとの収集結果から、Router → AP1/AP2 → Wi-Fi端末、およびRouterのポート → 有線端末を表示する。
- Grafanaで現在の状態と、指定した過去時刻の状態を確認できるようにする。
- 線は観測または確認済みの物理配線に基づく。DHCPリースやARPキャッシュだけで現在の接続線を作らない。
- Routerのスイッチ表が示すのは「そのポートの先にMACが見える」ことであり、途中に別のスイッチがないことまでは証明しない。

## 現在使える情報と不足分

| 入力 | 現状 | 用途 |
| --- | --- | --- |
| AP Web probe | APごとの接続端末MAC、ホスト名、SSID、チャンネル等を取得。現在はPrometheusの端末情報ラベルに出力 | APとWi-Fi端末の接続、および帯域 |
| Router probe | DHCP、ARP、スイッチMAC表の生応答を `data/router-probe/latest.json` に保存 | MACとRouterポートの対応、IP・候補名の補足 |
| `device-names.toml` | Pi上のroot専用MAC→表示名対応表 | 人が認識できる端末名 |
| Pi自身 | `eth0` のMACを取得可能 | Piの有線接続の照合 |

実測でPiの `eth0` MACはRouterのポート8に現れる。AP接続端末の多くはポート2または5に現れるが、AP1/AP2自身の管理MACまたは配線情報でポート対応を確定する必要がある。Windows PCは有線側MACを端末名対応表に登録して照合する。MACが見えない周期は線を推測しない。

AP probeに、成功した対象ごとの接続端末一覧と実際の収集時刻をroot専用スナップショットとして保存する処理を追加する。AP1とAP2は独立して成功・失敗を記録する。Routerの既存スナップショットは引き続き利用する。生の資格情報、SSID、MAC、IP、実端末名はGit管理しない。

## 収集・突合

既存のAP timerは5分境界、Router timerは30秒後に始まる。新しい `pi-lan-map` oneshot timerを各周期の3分30秒後に実行し、その周期に成功した入力だけを使う。収集が上限時間までかかった場合やprobeが失敗した場合も、その周期の結果を「未確認」として記録する。前周期の接続関係を今回の観測として流用しない。

1. APスナップショット、Routerスナップショット、probeの成否・試行時刻を読む。
2. MAC表記を小文字コロン区切りに正規化し、無効なMACや重複を除く。
3. APの接続一覧から `AP → Wi-Fi端末` を作る。スイッチ表のポートは補足するが、AP接続一覧がある端末を「有線端末」と重複表示しない。
4. スイッチ表にあるその他のMACを `Routerポート → 端末` とする。確認済みのAP管理MACやRouter自身のMACは端末一覧から除く。
5. APのポートは、管理IPのARP MACとRouterスイッチ表で確認した対応表に従って `Routerポート → AP` を作る。現状はAP1がポート2、AP2がポート5。
6. 名称は `device-names.toml` の名前、APホスト名、MACの順で決める。IPはAP情報またはARPの補足値として示し、接続判定には使わない。DHCPホスト名の解析は初期実装に含めない。

ノードIDは `router`、`apap1`、`apap2`、`mac<12桁の16進数>` のように名称から独立させる。異なるMACを同一端末として自動統合しない。複数MACを一つの端末名にまとめる場合は、将来、Pi内限定の明示的な端末ID対応を追加する。AP接続一覧にないMACがAPと同じRouterポートに見えても、有線と決めつけず「そのポートの先に学習されたMAC」と表示する。Piは自分の `eth0` MACで有線と確認できる。

## 履歴と時刻指定

Pi上の `data/lan-map/history.db` に専用SQLite DBを作る。Python標準ライブラリ `sqlite3` を使い、SQLite用のデーモン・サービス・追加Pythonパッケージは導入しない。

基本スキーマ:

| テーブル | 主な項目 | 役割 |
| --- | --- | --- |
| `snapshot` | `id`, `cycle_at`, `created_at` | 1周期を一意に記録。`cycle_at` を一意キーにして再実行時の重複を防ぐ |
| `source` | `snapshot_id`, Router/APのID、観測時刻・成否 | 入力ごとの鮮度を保存 |
| `node` | `snapshot_id`, `node_id`, 種別、表示名、MAC、IP、帯域、状態 | その周期で表示する機器 |
| `edge` | `snapshot_id`, `edge_id`, `source`, `target`, 根拠、Routerポート、状態 | その周期で表示する線 |

4テーブルは同じトランザクションで保存する。小規模で書き込みは5分に1回のため、最初はSQLite標準のロールバックジャーナルを使い、WALは必要が出た場合だけ検討する。DBはGit管理外。名前・識別子も当時の表示内容として各スナップショットに保存する。

Grafanaで時刻Tを指定したら、`cycle_at <= T` のうち最新の1件を検索し、表示したスナップショットの実時刻と各入力の観測時刻を必ず示す。Tから最後の周期まで5分以上の空白があれば「古い情報」と表示する。過去時刻に現在の端末名や接続関係を再適用しない。初期保持期間はPrometheusに合わせて2年とし、DBサイズ・実際の増加量を監視して調整する。バックアップはSQLiteのバックアップAPIなど、整合性を保てる方法で取得する。

## Grafana表示と追加依存

第一候補はGrafana用SQLiteデータソースプラグインを使い、DBをGrafanaコンテナへ読み取り専用でマウントする構成。プラグインは追加インストールが必要だが、別の常駐サービスやHTTP APIは増えない。GrafanaのNode graphに `node` と `edge` のクエリ結果を渡し、同じスナップショットの端末一覧表、収集時刻・成否表示を併設する。Grafana時間範囲の終了時刻をTとして使う。ダッシュボードは閲覧者を認証済みユーザーに限定する。

プラグイン4.0.6は現行Grafana 13.2.2/aarch64でインストール・登録済み。次にNode graphへ2つのSQL結果を渡せること、時刻指定が正しく反映されること、DBを読み取り専用マウントで開けることを小さなダミーDBで検証する。プラグインは他のGrafana可読ファイルにもアクセスし得るため、Grafana側のデータソース編集権限を管理者に限定し、既定の安全設定を緩めない。この検証が通らない場合は、SQLiteを読む小さな読み取り専用APIを代替案として比較する。その場合は常駐サービスが1つ増えるので、採用前に再評価する。

## 運用・検証

- `pi-lan-map.service` の成功、直近の周期、Router/AP別の観測鮮度、DB容量を監視する。Prometheusには成否・時刻・件数など集計値だけを公開し、新たなMAC・端末名ラベルは増やさない。
- 実データをGitやテストログに出さず、匿名化したfixtureでRouter表の解析、AP接続、Pi/Windows有線、MAC表記差、AP移動、欠測、再実行、指定時刻の検索をテストする。
- 実機ではAP管理MACとポートの対応、Piのポート8、Windows PCのMACとポートを確認する。各周期のAP接続台数と生成ノード数を照合し、失敗周期に古い線が残らないことを確認する。

参考: [Grafana Node graph](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/node-graph/)、[Grafana SQLiteデータソース](https://grafana.com/grafana/plugins/frser-sqlite-datasource/)。

# Wi-Fi Probe

Raspberry Piの内蔵Wi-Fiを4つのNetworkManagerプロファイルへ順番に接続し、AP・周波数帯ごとの品質を測定します。SSID、BSSID、パスワードはNetworkManager内だけで管理し、このプロジェクトの設定やメトリクスには出力しません。

## セットアップ

Piにuvをインストールした後、リポジトリのルートで実行します。

```bash
sudo ./scripts/install-wifi-probe.sh
```

この処理は、ロックファイルに従って `wifi-probe/.venv` を作成し、systemdユニットを配置します。タイマーは自動的には有効化しません。

## 手動確認

最初に、設定、必要なコマンド、有線デフォルトルート、NetworkManagerプロファイルを検証します。この操作ではWi-Fiへ接続しません。

```bash
sudo /mnt/data/pi_monitor/wifi-probe/.venv/bin/pi-wifi-probe \
  --config /mnt/data/pi_monitor/wifi-probe/config/probes.toml \
  --dry-run
```

対象を1つだけ測定する場合:

```bash
sudo /mnt/data/pi_monitor/wifi-probe/.venv/bin/pi-wifi-probe \
  --config /mnt/data/pi_monitor/wifi-probe/config/probes.toml \
  --target ap1_24
```

4系統を順番に測定する場合:

```bash
sudo /mnt/data/pi_monitor/wifi-probe/.venv/bin/pi-wifi-probe \
  --config /mnt/data/pi_monitor/wifi-probe/config/probes.toml \
  --all
```

手動実行でオプションを指定しなければ、状態ファイルを使って毎回1系統ずつローテーションします。
systemd timerからの定期実行では`--all`を指定し、毎回すべての系統を順番に測定します。

```bash
sudo /mnt/data/pi_monitor/wifi-probe/.venv/bin/pi-wifi-probe \
  --config /mnt/data/pi_monitor/wifi-probe/config/probes.toml
```

## 定期実行

手動測定に成功した後でタイマーを有効化します。

```bash
sudo systemctl enable --now pi-wifi-probe.timer
systemctl list-timers pi-wifi-probe.timer
journalctl -u pi-wifi-probe.service -n 100 --no-pager
```

systemd timerは5分ごとにすべての系統を順番に測定するため、各系統の測定開始はおよそ5分ごとです。
4系統は同時ではなく順番に接続するため、1回の測定内では数十秒のずれがあります。

## 出力

- Prometheusメトリクス: `/mnt/data/pi_monitor/data/node-exporter/textfile/wifi-<target>.prom`
- ローテーション状態: `/mnt/data/pi_monitor/data/wifi-probe/state.json`

測定中だけ送信元IP専用のルーティングテーブルを作り、インターネット向けの試験通信をWi-Fiへ流します。管理用のデフォルトルートは常に `eth0` のまま維持します。

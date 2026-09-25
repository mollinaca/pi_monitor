#!/usr/bin/env bash
set -euo pipefail

project_root=/mnt/data/pi_monitor
probe_root="$project_root/internet-speed-probe"

if [[ $EUID -ne 0 ]]; then
    echo "Run this installer as root." >&2
    exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required but was not found in PATH." >&2
    exit 1
fi
if ! command -v speedtest >/dev/null 2>&1; then
    echo "Ookla Speedtest CLI is required but was not found in PATH." >&2
    exit 1
fi

install -d -m 0755 "$project_root/data/node-exporter/textfile"

cd "$probe_root"
uv sync --locked --no-dev

install -m 0644 systemd/pi-internet-speed-probe.service /etc/systemd/system/
install -m 0644 systemd/pi-internet-speed-probe.timer /etc/systemd/system/
systemctl daemon-reload
if systemctl is-active --quiet pi-internet-speed-probe.timer; then
    systemctl restart pi-internet-speed-probe.timer
fi

echo "Internet speed probe installed."
echo "Run a manual probe before enabling the timer:"
echo "  systemctl start pi-internet-speed-probe.service"
echo "  journalctl -u pi-internet-speed-probe.service -n 50 --no-pager"
echo "Enable 30-minute scheduling after validation:"
echo "  systemctl enable --now pi-internet-speed-probe.timer"

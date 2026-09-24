#!/usr/bin/env bash
set -euo pipefail

project_root=/mnt/data/pi_monitor
probe_root="$project_root/ssd-smart-probe"

if [[ $EUID -ne 0 ]]; then
    echo "Run this installer as root." >&2
    exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required but was not found in PATH." >&2
    exit 1
fi
if ! command -v smartctl >/dev/null 2>&1; then
    echo "smartctl is required but was not found in PATH." >&2
    exit 1
fi

install -d -m 0755 "$project_root/data/node-exporter/textfile"

cd "$probe_root"
uv sync --locked --no-dev

install -m 0644 systemd/pi-ssd-smart-probe.service /etc/systemd/system/
install -m 0644 systemd/pi-ssd-smart-probe.timer /etc/systemd/system/
systemctl daemon-reload
if systemctl is-active --quiet pi-ssd-smart-probe.timer; then
    systemctl restart pi-ssd-smart-probe.timer
fi

echo "SSD SMART probe installed."
echo "Run a manual probe before enabling the daily timer:"
echo "  systemctl start pi-ssd-smart-probe.service"
echo "  journalctl -u pi-ssd-smart-probe.service -n 50 --no-pager"
echo "Enable daily scheduling after validation:"
echo "  systemctl enable --now pi-ssd-smart-probe.timer"

#!/usr/bin/env bash
set -euo pipefail

project_root=/mnt/data/pi_monitor

if [[ $EUID -ne 0 ]]; then
    echo "Run this installer as root." >&2
    exit 1
fi
if ! command -v vcgencmd >/dev/null 2>&1; then
    echo "vcgencmd is required but was not found in PATH." >&2
    exit 1
fi

install -d -m 0755 "$project_root/data/node-exporter/textfile"
install -m 0644 "$project_root/throttling-probe/systemd/pi-throttling-probe.service" /etc/systemd/system/
install -m 0644 "$project_root/throttling-probe/systemd/pi-throttling-probe.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now pi-throttling-probe.timer
systemctl start pi-throttling-probe.service

echo "Raspberry Pi throttling probe installed and started."

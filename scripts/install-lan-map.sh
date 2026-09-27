#!/usr/bin/env bash
set -euo pipefail

project_root=/mnt/data/pi_monitor

if [[ $EUID -ne 0 ]]; then
    echo "Run this installer as root." >&2
    exit 1
fi

install -d -m 0750 "$project_root/data/lan-map"
install -d -m 0755 "$project_root/data/node-exporter/textfile"
install -m 0644 "$project_root/lan-map/systemd/pi-lan-map.service" /etc/systemd/system/
install -m 0644 "$project_root/lan-map/systemd/pi-lan-map.timer" /etc/systemd/system/
systemctl daemon-reload
if systemctl is-active --quiet pi-lan-map.timer; then
    systemctl restart pi-lan-map.timer
fi

echo "LAN map installed. Validate manually, then enable the timer:"
echo "  systemctl start pi-lan-map.service"
echo "  systemctl enable --now pi-lan-map.timer"

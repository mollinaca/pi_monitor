#!/usr/bin/env bash
set -euo pipefail

project_root=/mnt/data/pi_monitor
probe_root="$project_root/wifi-probe"

if [[ $EUID -ne 0 ]]; then
    echo "Run this installer as root." >&2
    exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required but was not found in PATH." >&2
    exit 1
fi

install -d -m 0755 \
    "$project_root/data/node-exporter/textfile" \
    "$project_root/data/wifi-probe"

cd "$probe_root"
uv sync --locked --no-dev

install -m 0644 systemd/pi-wifi-probe.service /etc/systemd/system/
install -m 0644 systemd/pi-wifi-probe.timer /etc/systemd/system/
systemctl daemon-reload
if systemctl is-active --quiet pi-wifi-probe.timer; then
    systemctl restart pi-wifi-probe.timer
fi

echo "Wi-Fi probe installed."
echo "Validate it before enabling the timer:"
echo "  $probe_root/.venv/bin/pi-wifi-probe --config $probe_root/config/probes.toml --dry-run"
echo "  $probe_root/.venv/bin/pi-wifi-probe --config $probe_root/config/probes.toml --target ap1_24"
echo "Enable scheduling after validation:"
echo "  systemctl enable --now pi-wifi-probe.timer"

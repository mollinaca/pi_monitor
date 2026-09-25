#!/usr/bin/env bash
set -euo pipefail

project_root=/mnt/data/pi_monitor
probe_root="$project_root/ap-web-probe"
credentials_file=/root/.config/pi_monitor/ap-web-probe.toml

if [[ $EUID -ne 0 ]]; then
    echo "Run this installer as root." >&2
    exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required but was not found in PATH." >&2
    exit 1
fi
if [[ ! -f $credentials_file ]]; then
    echo "Create $credentials_file before installing; see ap-web-probe/README.md." >&2
    exit 1
fi
credentials_mode=$(stat -c '%a' "$credentials_file")
if (( (8#$credentials_mode & 077) != 0 )); then
    echo "$credentials_file must not be group/world readable." >&2
    exit 1
fi

install -d -m 0755 "$project_root/data/node-exporter/textfile"
cd "$probe_root"
uv sync --locked --no-dev
install -m 0644 systemd/pi-ap-web-probe.service /etc/systemd/system/
install -m 0644 systemd/pi-ap-web-probe.timer /etc/systemd/system/
systemctl daemon-reload
if systemctl is-active --quiet pi-ap-web-probe.timer; then
    systemctl restart pi-ap-web-probe.timer
fi

echo "AP web probe installed. Validate manually, then enable the timer:"
echo "  systemctl start pi-ap-web-probe.service"
echo "  systemctl enable --now pi-ap-web-probe.timer"

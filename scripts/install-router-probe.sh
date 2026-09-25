#!/usr/bin/env bash
set -euo pipefail

project_root=/mnt/data/pi_monitor
probe_root="$project_root/router-probe"
password_file=/root/.config/pi_monitor/router_password.txt

if [[ $EUID -ne 0 ]]; then
    echo "Run this installer as root." >&2
    exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required but was not found in PATH." >&2
    exit 1
fi
if [[ ! -f $password_file ]]; then
    echo "Create $password_file before installing." >&2
    exit 1
fi
password_mode=$(stat -c '%a' "$password_file")
if (( (8#$password_mode & 077) != 0 )); then
    echo "$password_file must not be group/world readable." >&2
    exit 1
fi

install -d -m 0755 "$project_root/data/node-exporter/textfile"
cd "$probe_root"
uv sync --locked --no-dev
install -m 0644 systemd/pi-router-probe.service /etc/systemd/system/
install -m 0644 systemd/pi-router-probe.timer /etc/systemd/system/
systemctl daemon-reload
if systemctl is-active --quiet pi-router-probe.timer; then
    systemctl restart pi-router-probe.timer
fi

echo "Router probe installed. Validate manually, then enable the timer:"
echo "  systemctl start pi-router-probe.service"
echo "  systemctl enable --now pi-router-probe.timer"

#!/bin/sh

set -eu

PROMETHEUS_IMAGE="prom/prometheus:v3.13.3"
PROMETHEUS_DATA_DIR="/mnt/data/pi_monitor/data/prometheus"
GRAFANA_IMAGE="grafana/grafana:13.2.2"
GRAFANA_DATA_DIR="/mnt/data/pi_monitor/data/grafana"
GRAFANA_SECRET_DIR="/root/.config/pi_monitor"
GRAFANA_SECRET_FILE="$GRAFANA_SECRET_DIR/grafana_admin_password"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this script as root (for example: sudo $0)." >&2
  exit 1
fi

prometheus_uid="$(docker run --rm --entrypoint /bin/id "$PROMETHEUS_IMAGE" -u nobody)"
prometheus_gid="$(docker run --rm --entrypoint /bin/id "$PROMETHEUS_IMAGE" -g nobody)"
grafana_uid="$(docker run --rm --entrypoint /usr/bin/id "$GRAFANA_IMAGE" -u grafana)"
grafana_gid="$(docker run --rm --entrypoint /usr/bin/id "$GRAFANA_IMAGE" -g grafana)"

case "$prometheus_uid:$prometheus_gid:$grafana_uid:$grafana_gid" in
  *[!0-9:]* | :* | *:)
    echo "Could not determine numeric Prometheus UID/GID." >&2
    exit 1
    ;;
esac

install -d \
  -m 0750 \
  -o "$prometheus_uid" \
  -g "$prometheus_gid" \
  "$PROMETHEUS_DATA_DIR"

install -d \
  -m 0750 \
  -o "$grafana_uid" \
  -g "$grafana_gid" \
  "$GRAFANA_DATA_DIR"

install -d -m 0700 -o 0 -g 0 "$GRAFANA_SECRET_DIR"
if [ -e "$GRAFANA_SECRET_FILE" ] && [ ! -s "$GRAFANA_SECRET_FILE" ]; then
  echo "Grafana password file exists but is empty: $GRAFANA_SECRET_FILE" >&2
  exit 1
fi
if [ ! -e "$GRAFANA_SECRET_FILE" ]; then
  umask 077
  tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32 > "$GRAFANA_SECRET_FILE"
  printf '\n' >> "$GRAFANA_SECRET_FILE"
fi
chown 0:0 "$GRAFANA_SECRET_FILE"
chmod 0440 "$GRAFANA_SECRET_FILE"

echo "Prepared $PROMETHEUS_DATA_DIR for Prometheus ($prometheus_uid:$prometheus_gid)."
echo "Prepared $GRAFANA_DATA_DIR for Grafana ($grafana_uid:$grafana_gid)."
echo "Prepared root-only Grafana admin password file."

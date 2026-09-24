#!/bin/sh

set -eu

PROMETHEUS_IMAGE="prom/prometheus:v3.13.3"
PROMETHEUS_DATA_DIR="/mnt/data/pi_monitor/data/prometheus"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this script as root (for example: sudo $0)." >&2
  exit 1
fi

prometheus_uid="$(docker run --rm --entrypoint /bin/id "$PROMETHEUS_IMAGE" -u nobody)"
prometheus_gid="$(docker run --rm --entrypoint /bin/id "$PROMETHEUS_IMAGE" -g nobody)"

case "$prometheus_uid:$prometheus_gid" in
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

echo "Prepared $PROMETHEUS_DATA_DIR for Prometheus ($prometheus_uid:$prometheus_gid)."

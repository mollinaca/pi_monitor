from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prometheus_client import CollectorRegistry, Gauge, write_to_textfile


@dataclass(frozen=True)
class Settings:
    speedtest_binary: Path
    interface: str
    server_id: int
    server_name: str
    server_location: str
    timeout_seconds: int
    metrics_directory: Path
    metrics_filename: str

    @property
    def metrics_path(self) -> Path:
        return self.metrics_directory / self.metrics_filename

    @property
    def labels(self) -> tuple[str, str, str, str]:
        return (self.interface, str(self.server_id), self.server_name, self.server_location)


def load_settings(path: Path) -> Settings:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    probe = data.get("probe")
    if not isinstance(probe, dict):
        raise ValueError("[probe] table is required")
    string_fields = (
        "speedtest_binary",
        "interface",
        "server_name",
        "server_location",
        "metrics_directory",
        "metrics_filename",
    )
    if any(not isinstance(probe.get(key), str) or not probe[key] for key in string_fields):
        raise ValueError("probe configuration contains missing or invalid string values")
    if not isinstance(probe.get("server_id"), int) or probe["server_id"] <= 0:
        raise ValueError("server_id must be a positive integer")
    if not isinstance(probe.get("timeout_seconds"), int) or probe["timeout_seconds"] <= 0:
        raise ValueError("timeout_seconds must be a positive integer")
    binary = Path(probe["speedtest_binary"])
    if not binary.is_absolute():
        raise ValueError("speedtest_binary must be an absolute path")
    filename = probe["metrics_filename"]
    if Path(filename).name != filename or not filename.endswith(".prom"):
        raise ValueError("metrics_filename must be a plain .prom filename")
    return Settings(
        speedtest_binary=binary,
        interface=probe["interface"],
        server_id=probe["server_id"],
        server_name=probe["server_name"],
        server_location=probe["server_location"],
        timeout_seconds=probe["timeout_seconds"],
        metrics_directory=Path(probe["metrics_directory"]),
        metrics_filename=filename,
    )


def parse_result(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("type") == "result":
            return payload
    return None


def run_speedtest(settings: Settings) -> tuple[int, dict[str, Any] | None, str, float]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            [
                str(settings.speedtest_binary),
                "--accept-license",
                "--accept-gdpr",
                f"--interface={settings.interface}",
                f"--server-id={settings.server_id}",
                "--format=json",
                "--progress=no",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=settings.timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, None, f"speedtest timed out after {settings.timeout_seconds}s: {exc}", time.monotonic() - started
    return (
        completed.returncode,
        parse_result(completed.stdout),
        completed.stderr.strip(),
        time.monotonic() - started,
    )


def numeric(payload: dict[str, Any], *keys: str) -> float | None:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return float(current) if isinstance(current, (int, float)) else None


def write_metrics(
    settings: Settings,
    *,
    command_exit_status: int,
    payload: dict[str, Any] | None,
    duration_seconds: float,
) -> Path:
    settings.metrics_directory.mkdir(parents=True, exist_ok=True)
    registry = CollectorRegistry()
    label_names = ("interface", "server_id", "server_name", "server_location")

    def gauge(name: str, documentation: str) -> Gauge:
        return Gauge(name, documentation, label_names, registry=registry)

    success = payload is not None and command_exit_status == 0
    gauge("home_internet_speedtest_probe_success", "1 if the fixed-server Ookla test succeeded").labels(*settings.labels).set(int(success))
    gauge("home_internet_speedtest_probe_timestamp_seconds", "Unix timestamp of the most recent speed test attempt").labels(*settings.labels).set(time.time())
    gauge("home_internet_speedtest_probe_duration_seconds", "Wall-clock duration of the most recent speed test attempt").labels(*settings.labels).set(duration_seconds)
    gauge("home_internet_speedtest_command_exit_status", "Speedtest CLI exit status from the most recent attempt").labels(*settings.labels).set(command_exit_status)

    if success and payload is not None:
        metric_values = (
            ("home_internet_speedtest_download_bytes_per_second", "Measured download throughput", numeric(payload, "download", "bandwidth")),
            ("home_internet_speedtest_upload_bytes_per_second", "Measured upload throughput", numeric(payload, "upload", "bandwidth")),
            ("home_internet_speedtest_ping_latency_milliseconds", "Idle ping latency reported by the speed test", numeric(payload, "ping", "latency")),
            ("home_internet_speedtest_ping_jitter_milliseconds", "Idle ping jitter reported by the speed test", numeric(payload, "ping", "jitter")),
            ("home_internet_speedtest_packet_loss_percent", "Packet loss percentage reported by the speed test when available", numeric(payload, "packetLoss")),
            ("home_internet_speedtest_downloaded_bytes", "Download test traffic generated by the most recent speed test", numeric(payload, "download", "bytes")),
            ("home_internet_speedtest_uploaded_bytes", "Upload test traffic generated by the most recent speed test", numeric(payload, "upload", "bytes")),
        )
        for name, documentation, value in metric_values:
            if value is not None:
                gauge(name, documentation).labels(*settings.labels).set(value)

    write_to_textfile(str(settings.metrics_path), registry)
    return settings.metrics_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect fixed-server Ookla speed test metrics")
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config)
        exit_status, payload, error, duration = run_speedtest(settings)
        destination = write_metrics(
            settings,
            command_exit_status=exit_status,
            payload=payload,
            duration_seconds=duration,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Internet speed probe failed before writing metrics: {exc}", file=sys.stderr)
        return 1
    if payload is None or exit_status != 0:
        print(f"Internet speed probe failed: {error or 'no Speedtest result JSON'}", file=sys.stderr)
        return 1
    print(f"Internet speed probe | server={settings.server_id} | metrics={destination}")
    return 0

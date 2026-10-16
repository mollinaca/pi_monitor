from __future__ import annotations

import argparse
import json
import math
import sqlite3
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
    timeout_seconds: int
    metrics_directory: Path
    metrics_filename: str
    history_path: Path

    @property
    def metrics_path(self) -> Path:
        return self.metrics_directory / self.metrics_filename


def load_settings(path: Path) -> Settings:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    probe = data.get("probe")
    if not isinstance(probe, dict):
        raise ValueError("[probe] table is required")
    string_fields = (
        "speedtest_binary",
        "interface",
        "history_path",
        "metrics_directory",
        "metrics_filename",
    )
    if any(not isinstance(probe.get(key), str) or not probe[key] for key in string_fields):
        raise ValueError("probe configuration contains missing or invalid string values")
    if not isinstance(probe.get("timeout_seconds"), int) or probe["timeout_seconds"] <= 0:
        raise ValueError("timeout_seconds must be a positive integer")
    binary = Path(probe["speedtest_binary"])
    if not binary.is_absolute():
        raise ValueError("speedtest_binary must be an absolute path")
    history_path = Path(probe["history_path"])
    if not history_path.is_absolute():
        raise ValueError("history_path must be an absolute path")
    filename = probe["metrics_filename"]
    if Path(filename).name != filename or not filename.endswith(".prom"):
        raise ValueError("metrics_filename must be a plain .prom filename")
    return Settings(
        speedtest_binary=binary,
        interface=probe["interface"],
        timeout_seconds=probe["timeout_seconds"],
        metrics_directory=Path(probe["metrics_directory"]),
        metrics_filename=filename,
        history_path=history_path,
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
    if isinstance(current, bool) or not isinstance(current, (int, float)):
        return None
    try:
        value = float(current)
    except OverflowError:
        return None
    return value if math.isfinite(value) else None


def valid_result(payload: dict[str, Any] | None) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("type") == "result"
        and all(
        numeric(payload, direction, "bandwidth") is not None
        for direction in ("download", "upload")
        )
        and isinstance(payload.get("server"), dict)
        and isinstance(payload["server"].get("id"), int)
        and payload["server"]["id"] > 0
    )


def server_labels(payload: dict[str, Any] | None) -> tuple[str, str, str]:
    if not valid_result(payload):
        return ("", "", "")
    server = payload["server"]
    return (str(server["id"]), str(server.get("name", "")), str(server.get("location", "")))


def write_history(settings: Settings, payload: dict[str, Any], measured_at: float) -> None:
    settings.history_path.parent.mkdir(parents=True, exist_ok=True)
    server_id, server_name, server_location = server_labels(payload)
    with sqlite3.connect(settings.history_path) as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS measurement (
                id INTEGER PRIMARY KEY,
                measured_at INTEGER NOT NULL,
                download_mbps REAL NOT NULL,
                upload_mbps REAL NOT NULL,
                server_id INTEGER NOT NULL,
                server_name TEXT NOT NULL,
                server_location TEXT NOT NULL
            )"""
        )
        connection.execute(
            "INSERT INTO measurement (measured_at, download_mbps, upload_mbps, server_id, server_name, server_location) VALUES (?, ?, ?, ?, ?, ?)",
            (int(measured_at), numeric(payload, "download", "bandwidth") * 8 / 1_000_000,
             numeric(payload, "upload", "bandwidth") * 8 / 1_000_000,
             int(server_id), server_name, server_location),
        )


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
    labels = (settings.interface, *server_labels(payload))

    def gauge(name: str, documentation: str) -> Gauge:
        return Gauge(name, documentation, label_names, registry=registry)

    success = valid_result(payload) and command_exit_status == 0
    gauge("home_internet_speedtest_probe_success", "1 if the Ookla test succeeded").labels(*labels).set(int(success))
    gauge("home_internet_speedtest_probe_timestamp_seconds", "Unix timestamp of the most recent speed test attempt").labels(*labels).set(time.time())
    gauge("home_internet_speedtest_probe_duration_seconds", "Wall-clock duration of the most recent speed test attempt").labels(*labels).set(duration_seconds)
    gauge("home_internet_speedtest_command_exit_status", "Speedtest CLI exit status from the most recent attempt").labels(*labels).set(command_exit_status)

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
                gauge(name, documentation).labels(*labels).set(value)

    write_to_textfile(str(settings.metrics_path), registry)
    return settings.metrics_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect Ookla speed test metrics")
    parser.add_argument("--config", required=True, type=Path)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 1
    try:
        settings = load_settings(args.config)
        exit_status, payload, error, duration = run_speedtest(settings)
        if exit_status == 0 and valid_result(payload):
            write_history(settings, payload, time.time())
        destination = write_metrics(
            settings,
            command_exit_status=exit_status,
            payload=payload,
            duration_seconds=duration,
        )
    except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"internet-speed stage=setup_or_write error={type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"internet-speed stage=unexpected error={type(exc).__name__}", file=sys.stderr)
        return 1
    if exit_status != 0 or not valid_result(payload):
        reason = "timeout" if exit_status == 124 else ("invalid_result" if exit_status == 0 else f"command_exit_{exit_status}")
        detail = " ".join(error.split())[:500]
        print(f"internet-speed stage=collect error={reason}" + (f" detail={detail}" if detail else ""), file=sys.stderr)
        return 1
    print(f"Internet speed probe | server={server_labels(payload)[0]} | metrics={destination}")
    return 0

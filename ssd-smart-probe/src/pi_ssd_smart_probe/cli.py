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
    device: str
    device_type: str
    metrics_directory: Path
    metrics_filename: str

    @property
    def metrics_path(self) -> Path:
        return self.metrics_directory / self.metrics_filename

    @property
    def device_label(self) -> str:
        return Path(self.device).name


def load_settings(path: Path) -> Settings:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    probe = data.get("probe")
    if not isinstance(probe, dict):
        raise ValueError("[probe] table is required")
    required = ("device", "device_type", "metrics_directory", "metrics_filename")
    if any(not isinstance(probe.get(key), str) or not probe[key] for key in required):
        raise ValueError("probe configuration contains missing or invalid values")
    device = probe["device"]
    if not device.startswith("/dev/"):
        raise ValueError("device must be an absolute path below /dev")
    filename = probe["metrics_filename"]
    if Path(filename).name != filename or not filename.endswith(".prom"):
        raise ValueError("metrics_filename must be a plain .prom filename")
    return Settings(
        device=device,
        device_type=probe["device_type"],
        metrics_directory=Path(probe["metrics_directory"]),
        metrics_filename=filename,
    )


def run_smartctl(settings: Settings) -> tuple[int, dict[str, Any] | None, str]:
    completed = subprocess.run(
        ["smartctl", "-j", "-a", "-d", settings.device_type, settings.device],
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return completed.returncode, None, completed.stderr.strip()
    if not isinstance(payload, dict):
        return completed.returncode, None, "smartctl did not return a JSON object"
    return completed.returncode, payload, completed.stderr.strip()


def attribute_raw_values(payload: dict[str, Any]) -> dict[int, int]:
    table = payload.get("ata_smart_attributes", {}).get("table", [])
    values: dict[int, int] = {}
    if not isinstance(table, list):
        return values
    for attribute in table:
        if not isinstance(attribute, dict):
            continue
        identifier = attribute.get("id")
        raw = attribute.get("raw", {}).get("value")
        if isinstance(identifier, int) and isinstance(raw, int):
            values[identifier] = raw
    return values


def nested_value(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def write_metrics(
    settings: Settings,
    *,
    command_exit_status: int,
    payload: dict[str, Any] | None,
) -> Path:
    settings.metrics_directory.mkdir(parents=True, exist_ok=True)
    registry = CollectorRegistry()
    labels = (settings.device_label,)

    def gauge(name: str, documentation: str) -> Gauge:
        return Gauge(name, documentation, ("device",), registry=registry)

    parsed = payload is not None
    gauge("home_ssd_smart_probe_success", "1 if smartctl returned parseable SMART JSON").labels(
        *labels
    ).set(int(parsed))
    gauge(
        "home_ssd_smart_probe_timestamp_seconds",
        "Unix timestamp of the most recent SMART probe attempt",
    ).labels(*labels).set(time.time())
    gauge(
        "home_ssd_smart_command_exit_status",
        "smartctl process exit status bitmask from the most recent probe",
    ).labels(*labels).set(command_exit_status)

    if payload is not None:
        smart_status = nested_value(payload, "smart_status", "passed")
        gauge(
            "home_ssd_smart_overall_passed",
            "1 if the device SMART overall-health assessment passed",
        ).labels(*labels).set(int(smart_status is True))

        optional_values = (
            (
                "home_ssd_smart_temperature_celsius",
                "Current SSD temperature reported by SMART",
                nested_value(payload, "temperature", "current"),
            ),
            (
                "home_ssd_smart_power_on_hours",
                "SSD power-on hours reported by SMART",
                nested_value(payload, "power_on_time", "hours"),
            ),
            (
                "home_ssd_smart_power_cycle_count",
                "SSD power-cycle count reported by SMART",
                payload.get("power_cycle_count"),
            ),
            (
                "home_ssd_smart_error_log_entries",
                "Number of entries in the SMART error log",
                nested_value(payload, "ata_smart_error_log", "summary", "count"),
            ),
            (
                "home_ssd_smart_self_test_passed",
                "1 if the most recent SMART self-test passed",
                int(nested_value(payload, "ata_smart_data", "self_test", "status", "passed") is True),
            ),
        )
        for name, documentation, value in optional_values:
            if isinstance(value, (int, float)):
                gauge(name, documentation).labels(*labels).set(value)

        attributes = attribute_raw_values(payload)
        attribute_metrics = (
            ("home_ssd_smart_reallocated_sectors", "Reallocated sector count", 5),
            ("home_ssd_smart_pending_sectors", "Current pending sector count", 197),
            ("home_ssd_smart_offline_uncorrectable_sectors", "Offline uncorrectable sector count", 198),
            ("home_ssd_smart_udma_crc_errors", "UDMA CRC error count", 199),
            ("home_ssd_smart_program_failures", "Total NAND program failure count", 181),
            ("home_ssd_smart_erase_failures", "Total NAND erase failure count", 182),
            (
                "home_ssd_smart_available_reserved_space_percent",
                "Vendor-reported available reserved space; this is not a lifetime prediction",
                232,
            ),
            (
                "home_ssd_smart_total_lbas_written_raw",
                "Vendor-reported raw Total_LBAs_Written counter; its unit is not interpreted",
                241,
            ),
        )
        for name, documentation, identifier in attribute_metrics:
            value = attributes.get(identifier)
            if value is not None:
                gauge(name, documentation).labels(*labels).set(value)
    else:
        gauge(
            "home_ssd_smart_overall_passed",
            "1 if the device SMART overall-health assessment passed",
        ).labels(*labels).set(0)

    write_to_textfile(str(settings.metrics_path), registry)
    return settings.metrics_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect external SSD SMART metrics")
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config)
        exit_status, payload, error = run_smartctl(settings)
        destination = write_metrics(
            settings, command_exit_status=exit_status, payload=payload
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"SSD SMART probe failed before writing metrics: {exc}", file=sys.stderr)
        return 1

    if payload is None:
        print(f"SSD SMART probe returned no parseable JSON: {error}", file=sys.stderr)
        return 1
    print(
        f"SSD SMART probe | parsed=true | smartctl_exit={exit_status} | metrics={destination}"
    )
    return 0

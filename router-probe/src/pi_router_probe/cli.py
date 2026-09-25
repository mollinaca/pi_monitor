from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pexpect
from prometheus_client import CollectorRegistry, Gauge, write_to_textfile


ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PROMPT = re.compile(r"(?:^|\r?\n)[>#]\s*$")
MORE = re.compile(r"(?:--[Mm]ore--|Press any key)")
MAC = re.compile(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", re.IGNORECASE)
NUMBER = r"([0-9][0-9,]*)"


@dataclass(frozen=True)
class Settings:
    password_file: Path
    metrics_directory: Path
    metrics_filename: str
    snapshot_directory: Path
    address: str
    username: str
    port: int
    timeout_seconds: int
    lan_interfaces: tuple[str, ...]

    @property
    def metrics_path(self) -> Path:
        return self.metrics_directory / self.metrics_filename


def load_settings(path: Path) -> Settings:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    probe, router = data.get("probe"), data.get("router")
    if not isinstance(probe, dict) or not isinstance(router, dict):
        raise ValueError("[probe] and [router] tables are required")
    required_probe = ("password_file", "metrics_directory", "metrics_filename", "snapshot_directory")
    if any(not isinstance(probe.get(key), str) or not probe[key] for key in required_probe):
        raise ValueError("probe configuration contains missing or invalid string values")
    filename = probe["metrics_filename"]
    if Path(filename).name != filename or not filename.endswith(".prom"):
        raise ValueError("metrics_filename must be a plain .prom filename")
    address, username = router.get("address"), router.get("username")
    port, timeout = router.get("port"), router.get("timeout_seconds")
    interfaces = router.get("lan_interfaces")
    if not isinstance(address, str) or not address or not isinstance(username, str) or not username:
        raise ValueError("router address and username are required")
    if not isinstance(port, int) or not 1 <= port <= 65535 or not isinstance(timeout, int) or timeout <= 0:
        raise ValueError("router port and timeout_seconds must be positive integers")
    if not isinstance(interfaces, list) or not interfaces or any(
        not isinstance(name, str) or not re.fullmatch(r"lan[0-9]+", name) for name in interfaces
    ):
        raise ValueError("lan_interfaces must be a non-empty list of lanN names")
    return Settings(
        Path(probe["password_file"]), Path(probe["metrics_directory"]), filename,
        Path(probe["snapshot_directory"]), address, username, port, timeout, tuple(interfaces),
    )


def load_password(path: Path) -> str:
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise ValueError(f"password file must not be group/world readable: {path}")
    password = path.read_text(encoding="utf-8").strip()
    if not password:
        raise ValueError("password file must not be empty")
    return password


class RouterSession:
    """Small prompt-driven SSH client for Yamaha's interactive CLI.

    The router rejects SSH exec requests, so commands must be sent after the
    normal interactive prompt.  Only fixed, read-only ``show`` commands are
    passed to this class.
    """

    def __init__(self, settings: Settings, password: str) -> None:
        self.settings = settings
        self.password = password
        self.child: pexpect.spawn | None = None

    def __enter__(self) -> "RouterSession":
        args = [
            "-tt", "-o", "BatchMode=no", "-o", "NumberOfPasswordPrompts=1",
            "-o", "StrictHostKeyChecking=yes", "-o", f"ConnectTimeout={self.settings.timeout_seconds}",
            "-p", str(self.settings.port), f"{self.settings.username}@{self.settings.address}",
        ]
        self.child = pexpect.spawn("/usr/bin/ssh", args, encoding="utf-8", timeout=self.settings.timeout_seconds)
        result = self.child.expect([re.compile(r"(?i)password:"), PROMPT, pexpect.EOF, pexpect.TIMEOUT])
        if result == 0:
            self.child.sendline(self.password)
            result = self.child.expect([PROMPT, pexpect.EOF, pexpect.TIMEOUT])
        if result != 0:
            raise RuntimeError("router SSH login did not reach the normal CLI prompt")
        return self

    def run(self, command: str) -> str:
        if self.child is None:
            raise RuntimeError("router SSH session is not connected")
        if not command.startswith("show "):
            raise ValueError("only read-only show commands are permitted")
        self.child.sendline(command)
        chunks: list[str] = []
        while True:
            result = self.child.expect([PROMPT, MORE, pexpect.EOF, pexpect.TIMEOUT])
            chunks.append(self.child.before)
            if result == 0:
                return clean_cli_output("".join(chunks), command)
            if result == 1:
                self.child.send(" ")
                continue
            raise RuntimeError(f"router command did not complete: {command}")

    def __exit__(self, *_: object) -> None:
        if self.child is not None:
            try:
                self.child.sendline("exit")
                self.child.close(force=True)
            finally:
                self.child = None


def clean_cli_output(value: str, command: str) -> str:
    text = ANSI_ESCAPE.sub("", value).replace("\r", "")
    lines = text.splitlines()
    if lines and lines[0].strip() == command:
        lines = lines[1:]
    return "\n".join(lines).strip()


def integer_match(text: str, patterns: Iterable[str]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def parse_environment(text: str) -> dict[str, float]:
    values: dict[str, float] = {}
    cpu = integer_match(text, (r"CPU(?:\s+utilization|\s+usage)?\s*[:=]\s*" + NUMBER + r"\s*%",))
    memory = integer_match(text, (r"Memory(?:\s+utilization|\s+usage)?\s*[:=]\s*" + NUMBER + r"\s*%",))
    if cpu is not None:
        values["cpu_percent"] = float(cpu)
    if memory is not None:
        values["memory_percent"] = float(memory)
    # Yamaha releases vary between an elapsed seconds field and a human-readable
    # boot timestamp. Export uptime only when the CLI gives an unambiguous count.
    uptime = integer_match(text, (r"(?:Uptime|Elapsed time).*?" + NUMBER + r"\s*(?:sec|seconds)",))
    if uptime is not None:
        values["uptime_seconds"] = float(uptime)
    return values


def parse_lan_counters(text: str) -> dict[str, float]:
    """Parse common Yamaha English CLI counter labels without inventing values."""
    fields = {
        "receive_bytes": (r"(?:Received|Receive)\s+(?:bytes|octets)\s*[:=]\s*" + NUMBER,),
        "transmit_bytes": (r"(?:Transmitted|Transmit|Sent)\s+(?:bytes|octets)\s*[:=]\s*" + NUMBER,),
        "receive_packets": (r"(?:Received|Receive)\s+packets\s*[:=]\s*" + NUMBER,),
        "transmit_packets": (r"(?:Transmitted|Transmit|Sent)\s+packets\s*[:=]\s*" + NUMBER,),
        "receive_errors": (r"(?:Received|Receive)\s+errors\s*[:=]\s*" + NUMBER,),
        "transmit_errors": (r"(?:Transmitted|Transmit|Sent)\s+errors\s*[:=]\s*" + NUMBER,),
    }
    return {name: float(value) for name, patterns in fields.items() if (value := integer_match(text, patterns)) is not None}


def count_table_rows(text: str, *, mac_only: bool = False) -> int:
    if mac_only:
        return sum(1 for line in text.splitlines() if MAC.search(line))
    # DHCP and ARP dynamic rows contain an IPv4 address. Exclude headings and
    # do not preserve addresses in metrics.
    return sum(1 for line in text.splitlines() if re.search(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b", line))


def collect(settings: Settings, password: str) -> tuple[dict[str, str], float]:
    commands = ["show environment", "show status dhcp", "show arp", "show status switching-hub macaddress"]
    commands.extend(f"show status {interface}" for interface in settings.lan_interfaces)
    started = time.monotonic()
    with RouterSession(settings, password) as session:
        responses = {command: session.run(command) for command in commands}
    return responses, time.monotonic() - started


def write_snapshot(settings: Settings, responses: dict[str, str]) -> None:
    settings.snapshot_directory.mkdir(parents=True, exist_ok=True)
    destination = settings.snapshot_directory / "latest.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"collected_at": time.time(), "responses": responses}, ensure_ascii=False), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(destination)


def write_metrics(settings: Settings, password: str) -> Path:
    settings.metrics_directory.mkdir(parents=True, exist_ok=True)
    registry = CollectorRegistry()
    success = Gauge("home_router_probe_success", "1 if the read-only router SSH probe succeeded", registry=registry)
    attempt = Gauge("home_router_probe_timestamp_seconds", "Unix timestamp of the latest router probe attempt", registry=registry)
    duration = Gauge("home_router_probe_duration_seconds", "Wall-clock duration of the latest router probe", registry=registry)
    cpu = Gauge("home_router_cpu_utilization_percent", "Router CPU utilization reported by show environment", registry=registry)
    memory = Gauge("home_router_memory_utilization_percent", "Router memory utilization reported by show environment", registry=registry)
    uptime = Gauge("home_router_uptime_seconds", "Router uptime when reported as seconds by the CLI", registry=registry)
    table_entries = Gauge("home_router_table_entries", "Current entries reported by router tables", ("table",), registry=registry)
    interface_counters = Gauge("home_router_interface_counter", "Router interface counters reported by show status lanN", ("interface", "counter"), registry=registry)
    attempt.set(time.time())
    started = time.monotonic()
    try:
        responses, elapsed = collect(settings, password)
        environment = parse_environment(responses["show environment"])
        for name, gauge in (("cpu_percent", cpu), ("memory_percent", memory), ("uptime_seconds", uptime)):
            if name in environment:
                gauge.set(environment[name])
        table_entries.labels("dhcp").set(count_table_rows(responses["show status dhcp"]))
        table_entries.labels("arp").set(count_table_rows(responses["show arp"]))
        table_entries.labels("switching_hub_mac").set(count_table_rows(responses["show status switching-hub macaddress"], mac_only=True))
        for interface in settings.lan_interfaces:
            for counter, value in parse_lan_counters(responses[f"show status {interface}"]).items():
                interface_counters.labels(interface, counter).set(value)
        write_snapshot(settings, responses)
        success.set(1)
        duration.set(elapsed)
    except (OSError, ValueError, RuntimeError, pexpect.ExceptionPexpect) as exc:
        print(f"Router probe failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        success.set(0)
        duration.set(time.monotonic() - started)
    write_to_textfile(str(settings.metrics_path), registry)
    os.chmod(settings.metrics_path, 0o644)
    return settings.metrics_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect read-only Yamaha router SSH metrics")
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config)
        destination = write_metrics(settings, load_password(settings.password_file))
    except (OSError, ValueError) as exc:
        print(f"Router probe failed before writing metrics: {exc}", file=sys.stderr)
        return 1
    print(f"Router probe metrics written to {destination}")
    return 0

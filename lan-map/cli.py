"""Build private, time-addressable LAN topology snapshots on the Pi."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import sqlite3
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAC = re.compile(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", re.IGNORECASE)
IPV4 = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")
PORT = re.compile(r"^\s*(?:--\s*)?port\s+(\d+):\d+\s*$", re.IGNORECASE)
DHCP_CLIENT_ID = re.compile(r"Client ID:\s*\(01\)\s*((?:[0-9a-fA-F]{2}\s+){5}[0-9a-fA-F]{2})", re.IGNORECASE)
DHCP_HOST_NAME = re.compile(r"Host Name:\s*(\S+)", re.IGNORECASE)
CYCLE_SECONDS = 300


@dataclass(frozen=True)
class AccessPoint:
    identifier: str
    name: str
    address: str
    router_port: int


@dataclass(frozen=True)
class Settings:
    router_snapshot: Path
    ap_snapshot_directory: Path
    device_names_file: Path
    pi_mac_file: Path
    pi_wifi_mac_file: Path
    database: Path
    metrics: Path
    access_points: tuple[AccessPoint, ...]
    retention_days: int = 730


def load_settings(path: Path) -> Settings:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    config = data.get("map")
    ap_data = data.get("access_points")
    if not isinstance(config, dict) or not isinstance(ap_data, list) or not ap_data:
        raise ValueError("[map] and [[access_points]] are required")
    keys = ("router_snapshot", "ap_snapshot_directory", "device_names_file", "pi_mac_file", "pi_wifi_mac_file", "database", "metrics")
    if any(not isinstance(config.get(key), str) or not config[key] for key in keys):
        raise ValueError("map paths must be non-empty strings")
    retention = config.get("retention_days", 730)
    if not isinstance(retention, int) or retention <= 0:
        raise ValueError("retention_days must be a positive integer")
    access_points: list[AccessPoint] = []
    seen: set[str] = set()
    for row in ap_data:
        if not isinstance(row, dict):
            raise ValueError("each access point must be a table")
        identifier, name, address, router_port = (row.get(key) for key in ("id", "name", "address", "router_port"))
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9_-]+", identifier) or identifier in seen:
            raise ValueError("access point id must be unique and contain only lowercase letters, digits, _ or -")
        if not isinstance(name, str) or not name or not isinstance(address, str) or not address:
            raise ValueError("access point name and address are required")
        if not isinstance(router_port, int) or router_port <= 0:
            raise ValueError("access point router_port must be positive")
        ipaddress.IPv4Address(address)
        seen.add(identifier)
        access_points.append(AccessPoint(identifier, name, address, router_port))
    return Settings(*(Path(config[key]) for key in keys), tuple(access_points), retention)


def load_device_names(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    if path.stat().st_mode & 0o077:
        raise ValueError("device-names.toml must not be group/world readable")
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    names: dict[str, str] = {}
    for entry in data.get("device", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("mac"), str) or not isinstance(entry.get("name"), str):
            raise ValueError("invalid device name entry")
        mac = entry["mac"].lower()
        if MAC.fullmatch(mac) is None or not entry["name"].strip() or mac in names:
            raise ValueError("invalid or duplicate device MAC/name")
        names[mac] = entry["name"].strip()
    return names


def parse_switch_ports(value: str) -> dict[str, int]:
    ports: dict[str, int] = {}
    current: int | None = None
    for line in value.splitlines():
        found = PORT.fullmatch(line)
        if found:
            current = int(found.group(1))
            continue
        if current is None:
            continue
        for match in MAC.finditer(line):
            ports[match.group(0).lower()] = current
    return ports


def parse_arp(value: str) -> dict[str, str]:
    addresses: dict[str, str] = {}
    for line in value.splitlines():
        mac = MAC.search(line)
        ip = IPV4.search(line)
        if mac is None or ip is None:
            continue
        try:
            ipaddress.IPv4Address(ip.group(0))
        except ipaddress.AddressValueError:
            continue
        addresses[mac.group(0).lower()] = ip.group(0)
    return addresses


def parse_dhcp_names(value: str) -> dict[str, str]:
    names: dict[str, str] = {}
    current_mac = ""
    for line in value.splitlines():
        if "Leased address:" in line:
            current_mac = ""
        client = DHCP_CLIENT_ID.search(line)
        if client:
            current_mac = ":".join(client.group(1).lower().split())
        host = DHCP_HOST_NAME.search(line)
        if host and current_mac:
            hostname = host.group(1).strip()
            if hostname.lower() not in {"unknown", "none", "-"}:
                names[current_mac] = hostname
    return names


def load_current(path: Path, cycle_at: int, source: str) -> tuple[dict[str, Any] | None, int | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        collected_at = int(value["collected_at"])
        if not cycle_at <= collected_at < cycle_at + CYCLE_SECONDS:
            return None, collected_at
        if source == "router" and not isinstance(value.get("responses"), dict):
            raise ValueError("router snapshot lacks responses")
        if source != "router" and (value.get("ap") != source or not isinstance(value.get("clients"), list)):
            raise ValueError("AP snapshot has wrong identifier or lacks clients")
        return value, collected_at
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        print(f"LAN map {source} snapshot unavailable: {type(exc).__name__}", file=sys.stderr)
        return None, None


def valid_ip(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    try:
        return str(ipaddress.IPv4Address(value.strip()))
    except ipaddress.AddressValueError:
        return ""


def band_for_channel(value: Any) -> str:
    try:
        channel = int(value)
    except (TypeError, ValueError):
        return "unknown"
    if 1 <= channel <= 14:
        return "2.4 GHz"
    if 32 <= channel <= 196:
        return "5 GHz"
    return "unknown"


def build_topology(
    settings: Settings,
    router: dict[str, Any] | None,
    aps: dict[str, dict[str, Any] | None],
    names: dict[str, str],
    pi_mac: str,
    pi_wifi_mac: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    nodes: dict[str, dict[str, str]] = {}
    edges: dict[str, dict[str, str]] = {}

    def node(identifier: str, title: str, subtitle: str, kind: str, **details: str) -> None:
        nodes[identifier] = {"id": identifier, "title": title, "subtitle": subtitle, "kind": kind, **details}

    def edge(source: str, target: str, evidence: str, **details: str) -> None:
        identifier = "e" + hashlib.sha256(f"{source}\0{target}".encode()).hexdigest()[:24]
        edges[identifier] = {"id": identifier, "source": source, "target": target, "evidence": evidence, **details}

    node("router", "Router", "RTX1210", "router", status="observed" if router else "unavailable")
    switch: dict[str, int] = {}
    arp: dict[str, str] = {}
    dhcp_names: dict[str, str] = {}
    if router:
        responses = router["responses"]
        switch = parse_switch_ports(str(responses.get("show status switching-hub macaddress", "")))
        arp = parse_arp(str(responses.get("show arp", "")))
        dhcp_names = parse_dhcp_names(str(responses.get("show status dhcp", "")))

    ap_management_macs = {mac for ap in settings.access_points for mac, ip in arp.items() if ip == ap.address}
    ap_clients: dict[str, tuple[AccessPoint, dict[str, Any], float]] = {}
    for ap in settings.access_points:
        snapshot = aps.get(ap.identifier)
        status = "observed" if snapshot else "unavailable"
        ap_id = f"ap{ap.identifier}"
        node(ap_id, ap.name, "Access point", "ap", ip=ap.address, status=status)
        port_id = f"port{ap.router_port}"
        node(port_id, f"Port {ap.router_port}", "Router LAN1", "port", status="configured")
        edge("router", port_id, "configured_port")
        edge(port_id, ap_id, "verified_ap_port")
        if not snapshot:
            continue
        for record in snapshot["clients"]:
            if not isinstance(record, dict) or not isinstance(record.get("mac"), str):
                continue
            mac = record["mac"].lower()
            if MAC.fullmatch(mac) is None:
                continue
            current = ap_clients.get(mac)
            observed = float(snapshot["collected_at"])
            if current is None or observed > current[2]:
                ap_clients[mac] = (ap, record, observed)

    for mac, (ap, record, _) in ap_clients.items():
        hostname = record.get("hostname") if isinstance(record.get("hostname"), str) else ""
        hostname = hostname.strip()
        if hostname.lower() == "unknown":
            hostname = ""
        title = "Raspberry Pi (Wi-Fi)" if mac == pi_wifi_mac else names.get(mac) or hostname or dhcp_names.get(mac) or ("Raspberry Pi" if mac == pi_mac else mac)
        band = band_for_channel(record.get("channel"))
        ip = valid_ip(record.get("ip")) or arp.get(mac, "")
        mac_id = "mac" + mac.replace(":", "")
        node(mac_id, title, band, "wifi", mac=mac, ip=ip, band=band, router_port="" if mac == pi_wifi_mac else str(switch.get(mac, "")), status="observed")
        edge(f"ap{ap.identifier}", mac_id, "ap_association", band=band)

    for mac, port in switch.items():
        if mac in ap_clients or mac in ap_management_macs or mac == pi_wifi_mac:
            continue
        port_id = f"port{port}"
        if port_id not in nodes:
            node(port_id, f"Port {port}", "Router LAN1", "port", status="observed")
            edge("router", port_id, "switch_table")
        title = names.get(mac) or ("Raspberry Pi" if mac == pi_mac else dhcp_names.get(mac) or mac)
        mac_id = "mac" + mac.replace(":", "")
        kind = "wired" if mac == pi_mac else "port_learned"
        subtitle = "Wired eth0" if kind == "wired" else "Seen behind Router port"
        node(mac_id, title, subtitle, kind, mac=mac, ip=arp.get(mac, ""), router_port=str(port), status="learned")
        edge(port_id, mac_id, "switch_table")

    return list(nodes.values()), list(edges.values())


SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot (
    id INTEGER PRIMARY KEY,
    cycle_at INTEGER NOT NULL UNIQUE,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS source (
    snapshot_id INTEGER NOT NULL REFERENCES snapshot(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL,
    observed_at INTEGER,
    status TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, source_id)
);
CREATE TABLE IF NOT EXISTS node (
    snapshot_id INTEGER NOT NULL REFERENCES snapshot(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    title TEXT NOT NULL,
    subtitle TEXT NOT NULL,
    kind TEXT NOT NULL,
    mac TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT '',
    band TEXT NOT NULL DEFAULT '',
    router_port TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (snapshot_id, id)
);
CREATE TABLE IF NOT EXISTS edge (
    snapshot_id INTEGER NOT NULL REFERENCES snapshot(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    evidence TEXT NOT NULL,
    band TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (snapshot_id, id)
);
"""


def save_snapshot(
    settings: Settings,
    cycle_at: int,
    created_at: int,
    sources: dict[str, tuple[dict[str, Any] | None, int | None]],
    nodes: list[dict[str, str]],
    edges: list[dict[str, str]],
) -> None:
    settings.database.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.database, timeout=5)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.executescript(SCHEMA)
        with connection:
            connection.execute("DELETE FROM snapshot WHERE cycle_at=?", (cycle_at,))
            cursor = connection.execute("INSERT INTO snapshot(cycle_at, created_at) VALUES(?, ?)", (cycle_at, created_at))
            snapshot_id = cursor.lastrowid
            connection.executemany(
                "INSERT INTO source(snapshot_id, source_id, observed_at, status) VALUES(?, ?, ?, ?)",
                ((snapshot_id, source, observed, "observed" if value else "unavailable") for source, (value, observed) in sources.items()),
            )
            connection.executemany(
                "INSERT INTO node(snapshot_id, id, title, subtitle, kind, mac, ip, band, router_port, status) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ((snapshot_id, *(entry.get(key, "") for key in ("id", "title", "subtitle", "kind", "mac", "ip", "band", "router_port", "status"))) for entry in nodes),
            )
            connection.executemany(
                "INSERT INTO edge(snapshot_id, id, source, target, evidence, band) VALUES(?, ?, ?, ?, ?, ?)",
                ((snapshot_id, *(entry.get(key, "") for key in ("id", "source", "target", "evidence", "band"))) for entry in edges),
            )
            connection.execute("DELETE FROM snapshot WHERE cycle_at < ?", (created_at - settings.retention_days * 86400,))
        os.chmod(settings.database, 0o640)
    finally:
        connection.close()


def write_metrics(path: Path, created_at: int, sources: dict[str, tuple[dict[str, Any] | None, int | None]], node_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# TYPE home_lan_map_timestamp_seconds gauge",
        f"home_lan_map_timestamp_seconds {created_at}",
        "# TYPE home_lan_map_nodes gauge",
        f"home_lan_map_nodes {node_count}",
        "# TYPE home_lan_map_source_fresh gauge",
    ]
    lines.extend(f'home_lan_map_source_fresh{{source="{source}"}} {1 if value else 0}' for source, (value, _) in sources.items())
    temporary = path.with_suffix(".prom.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o644)
    temporary.replace(path)


def read_mac(path: Path) -> str:
    try:
        mac = path.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return ""
    return mac if MAC.fullmatch(mac) else ""


def run(settings: Settings, now: float | None = None) -> tuple[int, int, tuple[str, ...]]:
    now = time.time() if now is None else now
    cycle_at = int(now // CYCLE_SECONDS * CYCLE_SECONDS)
    sources = {"router": load_current(settings.router_snapshot, cycle_at, "router")}
    for ap in settings.access_points:
        sources[ap.identifier] = load_current(settings.ap_snapshot_directory / f"{ap.identifier}.json", cycle_at, ap.identifier)
    names = load_device_names(settings.device_names_file)
    pi_mac = read_mac(settings.pi_mac_file)
    pi_wifi_mac = read_mac(settings.pi_wifi_mac_file)
    nodes, edges = build_topology(
        settings,
        sources["router"][0],
        {ap.identifier: sources[ap.identifier][0] for ap in settings.access_points},
        names,
        pi_mac,
        pi_wifi_mac,
    )
    save_snapshot(settings, cycle_at, int(now), sources, nodes, edges)
    write_metrics(settings.metrics, int(now), sources, len(nodes))
    unavailable = tuple(source for source, (snapshot, _) in sources.items() if snapshot is None)
    return len(nodes), len(edges), unavailable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a private LAN map snapshot")
    parser.add_argument("--config", required=True, type=Path)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 1
    try:
        nodes, edges, unavailable = run(load_settings(args.config))
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"lan-map stage=build_or_write error={type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"lan-map stage=unexpected error={type(exc).__name__}", file=sys.stderr)
        return 1
    if unavailable:
        print(f"lan-map stage=source error=unavailable sources={','.join(unavailable)}", file=sys.stderr)
        return 1
    print(f"LAN map snapshot saved: {nodes} nodes, {edges} edges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

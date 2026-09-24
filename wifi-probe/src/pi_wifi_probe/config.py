from __future__ import annotations

import ipaddress
import re
import tomllib
from pathlib import Path
from typing import Any

from .model import Config, Settings, Target


class ConfigError(ValueError):
    pass


_FORBIDDEN_KEYS = {"ssid", "bssid", "password", "passphrase", "psk"}
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_INTERFACE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")


def _reject_private_keys(value: Any, location: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in _FORBIDDEN_KEYS:
                raise ConfigError(
                    f"{location}.{key} must stay in NetworkManager and must not be stored here"
                )
            _reject_private_keys(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_private_keys(child, f"{location}[{index}]")


def _required(mapping: dict[str, Any], key: str, expected_type: type) -> Any:
    if key not in mapping:
        raise ConfigError(f"missing required setting: {key}")
    value = mapping[key]
    if not isinstance(value, expected_type) or isinstance(value, bool):
        raise ConfigError(f"{key} must be {expected_type.__name__}")
    return value


def load_config(path: Path) -> Config:
    try:
        with path.open("rb") as stream:
            raw = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot load {path}: {exc}") from exc

    _reject_private_keys(raw)
    probe = raw.get("probe")
    raw_targets = raw.get("targets")
    if not isinstance(probe, dict):
        raise ConfigError("[probe] table is required")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise ConfigError("at least one [[targets]] table is required")

    interface = _required(probe, "interface", str)
    management_interface = _required(probe, "management_interface", str)
    country = _required(probe, "country", str)
    gateway = _required(probe, "gateway", str)
    internet_target = _required(probe, "internet_target", str)
    for name, value in (
        ("interface", interface),
        ("management_interface", management_interface),
    ):
        if not _INTERFACE_PATTERN.fullmatch(value):
            raise ConfigError(f"invalid {name}: {value!r}")
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise ConfigError("country must be a two-letter uppercase country code")
    for name, value in (("gateway", gateway), ("internet_target", internet_target)):
        try:
            ipaddress.ip_address(value)
        except ValueError as exc:
            raise ConfigError(f"{name} must be an IP address") from exc

    settings = Settings(
        interface=interface,
        management_interface=management_interface,
        country=country,
        gateway=gateway,
        internet_target=internet_target,
        ping_count=_required(probe, "ping_count", int),
        ping_timeout_seconds=_required(probe, "ping_timeout_seconds", int),
        connect_timeout_seconds=_required(probe, "connect_timeout_seconds", int),
        route_table=_required(probe, "route_table", int),
        route_rule_priority=_required(probe, "route_rule_priority", int),
        metrics_directory=Path(_required(probe, "metrics_directory", str)),
        state_path=Path(_required(probe, "state_path", str)),
        lock_path=Path(_required(probe, "lock_path", str)),
    )
    if settings.ping_count < 1 or settings.ping_timeout_seconds < 1:
        raise ConfigError("ping settings must be positive")
    if settings.connect_timeout_seconds < 1:
        raise ConfigError("connect_timeout_seconds must be positive")
    if not 1 <= settings.route_table <= 2**32 - 1:
        raise ConfigError("route_table is out of range")
    for name, value in (
        ("metrics_directory", settings.metrics_directory),
        ("state_path", settings.state_path),
        ("lock_path", settings.lock_path),
    ):
        if not value.is_absolute():
            raise ConfigError(f"{name} must be an absolute path")

    targets: list[Target] = []
    ids: set[str] = set()
    connections: set[str] = set()
    for index, item in enumerate(raw_targets):
        if not isinstance(item, dict):
            raise ConfigError(f"targets[{index}] must be a table")
        target = Target(
            id=_required(item, "id", str),
            ap=_required(item, "ap", str),
            band=_required(item, "band", str),
            connection=_required(item, "connection", str),
        )
        if not _ID_PATTERN.fullmatch(target.id):
            raise ConfigError(f"invalid target id: {target.id!r}")
        if target.id in ids:
            raise ConfigError(f"duplicate target id: {target.id}")
        if target.connection in connections:
            raise ConfigError(f"duplicate connection profile: {target.connection}")
        ids.add(target.id)
        connections.add(target.connection)
        targets.append(target)

    return Config(settings=settings, targets=tuple(targets))

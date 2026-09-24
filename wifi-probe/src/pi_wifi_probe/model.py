from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Target:
    id: str
    ap: str
    band: str
    connection: str


@dataclass(frozen=True)
class Settings:
    interface: str
    management_interface: str
    country: str
    gateway: str
    internet_target: str
    ping_count: int
    ping_timeout_seconds: int
    connect_timeout_seconds: int
    route_table: int
    route_rule_priority: int
    metrics_directory: Path
    state_path: Path
    lock_path: Path


@dataclass(frozen=True)
class Config:
    settings: Settings
    targets: tuple[Target, ...]


@dataclass
class ProbeResult:
    target: Target
    timestamp: float
    duration_seconds: float = 0.0
    success: bool = False
    association_success: bool = False
    gateway_ping_success: bool = False
    internet_ping_success: bool = False
    association_duration_seconds: float | None = None
    signal_dbm: float | None = None
    frequency_mhz: int | None = None
    channel: int | None = None
    rx_bitrate_mbps: float | None = None
    tx_bitrate_mbps: float | None = None
    tx_failed_packets: int | None = None
    gateway_packet_loss_ratio: float | None = None
    gateway_latency_seconds: float | None = None
    internet_packet_loss_ratio: float | None = None
    internet_latency_seconds: float | None = None
    failed_stage: str = "none"

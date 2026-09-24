from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PingStats:
    packet_loss_ratio: float
    average_seconds: float | None


@dataclass(frozen=True)
class LinkStats:
    signal_dbm: float | None = None
    frequency_mhz: int | None = None
    channel: int | None = None
    rx_bitrate_mbps: float | None = None
    tx_bitrate_mbps: float | None = None
    tx_failed_packets: int | None = None


def frequency_to_channel(frequency_mhz: int) -> int | None:
    if frequency_mhz == 2484:
        return 14
    if 2412 <= frequency_mhz <= 2472:
        return (frequency_mhz - 2407) // 5
    if 5000 <= frequency_mhz <= 5895:
        return (frequency_mhz - 5000) // 5
    if 5955 <= frequency_mhz <= 7115:
        return (frequency_mhz - 5950) // 5
    return None


def parse_ping(output: str) -> PingStats:
    packets = re.search(r"(\d+) packets transmitted, (\d+) received", output)
    if packets is None:
        raise ValueError("ping packet summary not found")
    transmitted = int(packets.group(1))
    received = int(packets.group(2))
    if transmitted < 1 or received > transmitted:
        raise ValueError("invalid ping packet summary")
    average_seconds: float | None = None
    timing = re.search(
        r"(?:rtt|round-trip) min/avg/max/(?:mdev|stddev) = "
        r"[0-9.]+/([0-9.]+)/[0-9.]+/[0-9.]+ ms",
        output,
    )
    if timing is not None:
        average_seconds = float(timing.group(1)) / 1000.0
    return PingStats(
        packet_loss_ratio=(transmitted - received) / transmitted,
        average_seconds=average_seconds,
    )


def parse_link(link_output: str, station_output: str) -> LinkStats:
    def number(pattern: str, text: str) -> float | None:
        match = re.search(pattern, text, re.MULTILINE)
        return float(match.group(1)) if match else None

    frequency = number(r"^\s*freq:\s*(\d+)", link_output)
    signal = number(r"^\s*signal:\s*(-?[0-9.]+)\s+dBm", station_output)
    if signal is None:
        signal = number(r"^\s*signal:\s*(-?[0-9.]+)\s+dBm", link_output)
    rx_bitrate = number(r"^\s*rx bitrate:\s*([0-9.]+)\s+MBit/s", station_output)
    if rx_bitrate is None:
        rx_bitrate = number(r"^\s*rx bitrate:\s*([0-9.]+)\s+MBit/s", link_output)
    tx_bitrate = number(r"^\s*tx bitrate:\s*([0-9.]+)\s+MBit/s", station_output)
    if tx_bitrate is None:
        tx_bitrate = number(r"^\s*tx bitrate:\s*([0-9.]+)\s+MBit/s", link_output)
    tx_failed = number(r"^\s*tx failed:\s*(\d+)", station_output)
    frequency_int = int(frequency) if frequency is not None else None
    return LinkStats(
        signal_dbm=signal,
        frequency_mhz=frequency_int,
        channel=frequency_to_channel(frequency_int) if frequency_int else None,
        rx_bitrate_mbps=rx_bitrate,
        tx_bitrate_mbps=tx_bitrate,
        tx_failed_packets=int(tx_failed) if tx_failed is not None else None,
    )

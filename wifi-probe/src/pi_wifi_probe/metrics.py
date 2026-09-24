from __future__ import annotations

from pathlib import Path

from prometheus_client import CollectorRegistry, Gauge, write_to_textfile

from .model import ProbeResult


def write_metrics(
    result: ProbeResult,
    metrics_directory: Path,
    last_success_timestamp: float,
) -> Path:
    metrics_directory.mkdir(parents=True, exist_ok=True)
    registry = CollectorRegistry()
    label_names = ("target", "ap", "band")
    labels = (result.target.id, result.target.ap, result.target.band)

    def gauge(name: str, documentation: str) -> Gauge:
        return Gauge(name, documentation, label_names, registry=registry)

    gauge("home_wifi_probe_success", "1 if the complete Wi-Fi probe succeeded").labels(
        *labels
    ).set(int(result.success))
    stage_success = Gauge(
        "home_wifi_probe_stage_success",
        "1 if a Wi-Fi probe stage succeeded",
        (*label_names, "stage"),
        registry=registry,
    )
    for stage, succeeded in (
        ("association", result.association_success),
        ("gateway_ping", result.gateway_ping_success),
        ("internet_ping", result.internet_ping_success),
    ):
        stage_success.labels(*labels, stage).set(int(succeeded))

    gauge(
        "home_wifi_probe_timestamp_seconds",
        "Unix timestamp of the most recent probe attempt",
    ).labels(*labels).set(result.timestamp)
    gauge(
        "home_wifi_probe_last_success_timestamp_seconds",
        "Unix timestamp of the most recent successful probe",
    ).labels(*labels).set(last_success_timestamp)
    gauge("home_wifi_probe_duration_seconds", "Total duration of the probe").labels(
        *labels
    ).set(result.duration_seconds)

    optional_metrics = (
        (
            "home_wifi_association_duration_seconds",
            "Time required to associate and obtain an address",
            result.association_duration_seconds,
        ),
        ("home_wifi_signal_dbm", "Wi-Fi signal strength in dBm", result.signal_dbm),
        (
            "home_wifi_frequency_mhz",
            "Connected Wi-Fi frequency in MHz",
            result.frequency_mhz,
        ),
        ("home_wifi_channel", "Connected Wi-Fi channel", result.channel),
        (
            "home_wifi_rx_bitrate_mbps",
            "Current receive link bitrate in Mbit/s",
            result.rx_bitrate_mbps,
        ),
        (
            "home_wifi_tx_bitrate_mbps",
            "Current transmit link bitrate in Mbit/s",
            result.tx_bitrate_mbps,
        ),
        (
            "home_wifi_tx_failed_packets",
            "Transmit failures observed during the association",
            result.tx_failed_packets,
        ),
        (
            "home_wifi_gateway_packet_loss_ratio",
            "Packet loss ratio to the LAN gateway",
            result.gateway_packet_loss_ratio,
        ),
        (
            "home_wifi_gateway_latency_seconds",
            "Average ICMP latency to the LAN gateway",
            result.gateway_latency_seconds,
        ),
        (
            "home_wifi_internet_packet_loss_ratio",
            "Packet loss ratio to the configured internet target",
            result.internet_packet_loss_ratio,
        ),
        (
            "home_wifi_internet_latency_seconds",
            "Average ICMP latency to the configured internet target",
            result.internet_latency_seconds,
        ),
    )
    for name, documentation, value in optional_metrics:
        if value is not None:
            gauge(name, documentation).labels(*labels).set(value)

    destination = metrics_directory / f"wifi-{result.target.id}.prom"
    write_to_textfile(str(destination), registry)
    return destination

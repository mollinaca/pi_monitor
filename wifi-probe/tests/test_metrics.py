from pathlib import Path

from pi_wifi_probe.metrics import write_metrics
from pi_wifi_probe.model import ProbeResult, Target


def test_write_metrics_does_not_expose_wireless_identifiers(tmp_path: Path) -> None:
    target = Target(
        id="ap1_50",
        ap="AP-1F",
        band="5GHz",
        connection="pi-monitor-ap1-50",
    )
    result = ProbeResult(
        target=target,
        timestamp=1234.0,
        duration_seconds=2.5,
        success=True,
        association_success=True,
        gateway_ping_success=True,
        internet_ping_success=True,
        signal_dbm=-73,
        frequency_mhz=5520,
        channel=104,
        tx_bitrate_mbps=292.5,
    )
    path = write_metrics(result, tmp_path, last_success_timestamp=1234.0)
    output = path.read_text(encoding="utf-8")
    assert 'target="ap1_50"' in output
    assert 'ap="AP-1F"' in output
    assert "home_wifi_signal_dbm" in output
    assert "ssid" not in output.lower()
    assert "bssid" not in output.lower()
    assert "pi-monitor-ap1-50" not in output

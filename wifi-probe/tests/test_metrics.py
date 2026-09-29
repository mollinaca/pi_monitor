from pathlib import Path

from pi_wifi_probe.cli import _collection_failed, run
from pi_wifi_probe.config import ConfigError
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


def test_packet_loss_is_a_measured_condition_not_a_collection_error() -> None:
    target = Target("ap1_50", "AP-1F", "5GHz", "pi-monitor-ap1-50")
    assert not _collection_failed(ProbeResult(target, timestamp=1, success=False, failed_stage="connectivity"))
    assert _collection_failed(ProbeResult(target, timestamp=1, success=False, failed_stage="association"))


def test_configuration_and_argument_errors_exit_one(monkeypatch, capsys) -> None:
    assert run(["--invalid-option"]) == 1
    monkeypatch.setattr("pi_wifi_probe.cli.load_config", lambda _path: (_ for _ in ()).throw(ConfigError("invalid config")))
    assert run(["--config", "missing.toml"]) == 1
    assert "invalid config" in capsys.readouterr().err

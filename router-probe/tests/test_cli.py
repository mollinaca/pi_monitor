from pathlib import Path

import pytest

from pi_router_probe.cli import Settings, clean_cli_output, count_table_rows, load_settings, parse_environment, parse_lan_counters, write_metrics


def test_parse_environment_extracts_rtx1210_uptime() -> None:
    result = parse_environment("CPU: 17%(5sec)\nMemory: 42% used\nElapsed time from boot: 380days 14:26:06")
    assert result == {"cpu_percent": 17.0, "memory_percent": 42.0, "uptime_seconds": 32883966.0}


def test_parse_lan_counters() -> None:
    text = """Transmitted: 10 packets (5,678 octets)\nReceived: 11 packets (1,234 octets)\nReceive overflow: 0"""
    assert parse_lan_counters(text) == {
        "receive_bytes": 1234.0,
        "transmit_bytes": 5678.0,
        "receive_packets": 11.0,
        "transmit_packets": 10.0,
        "receive_overflow": 0.0,
    }


def test_count_table_rows_does_not_retain_values() -> None:
    assert count_table_rows("header\nentry 192.0.2.1\nentry 198.51.100.2") == 2
    assert count_table_rows("header\n00:11:22:33:44:55 x\n00:11:22:33:44:66", mac_only=True) == 2


def test_clean_cli_output_removes_echo_and_ansi() -> None:
    assert clean_cli_output("show environment\r\n\x1b[31mCPU: 1%\x1b[0m\r\n", "show environment") == "CPU: 1%"


def test_load_settings_rejects_non_lan_interfaces(tmp_path: Path) -> None:
    config = tmp_path / "probe.toml"
    config.write_text(
        """[probe]\npassword_file = \"/tmp/password\"\nmetrics_directory = \"/tmp/metrics\"\nmetrics_filename = \"router.prom\"\nsnapshot_directory = \"/tmp/snapshot\"\n[router]\naddress = \"router\"\nusername = \"user\"\nport = 22\ntimeout_seconds = 30\nlan_interfaces = [\"eth0\"]\n"""
    )
    with pytest.raises(ValueError, match="lan_interfaces"):
        load_settings(config)


def test_failed_collection_does_not_emit_zero_resource_values(tmp_path: Path, monkeypatch, capsys) -> None:
    from pi_router_probe import cli

    settings = Settings(tmp_path / "password", tmp_path, "router.prom", tmp_path / "snapshot", "router", "user", 22, 30, ("lan1",))

    def fail(*_args: object) -> tuple[dict[str, str], float]:
        raise RuntimeError("router SSH session is not connected")

    monkeypatch.setattr(cli, "collect", fail)
    failures: list[str] = []
    output = write_metrics(settings, "password", failures)
    contents = output.read_text(encoding="utf-8")
    assert failures == ["RuntimeError"]
    assert "home_router_probe_success 0.0" in contents
    assert "home_router_cpu_utilization_percent" not in contents
    assert "stage=collect" in capsys.readouterr().err


@pytest.mark.parametrize("failed_command", ["show status dhcp", "show arp", "show status switching-hub macaddress"])
def test_router_error_response_leaves_inventory_metrics_missing(tmp_path: Path, monkeypatch, failed_command: str) -> None:
    from pi_router_probe import cli

    settings = Settings(tmp_path / "password", tmp_path, "router.prom", tmp_path / "snapshot", "router", "user", 22, 30, ("lan1",))
    responses = {
        "show environment": "CPU: 10%\nMemory: 20%\nElapsed time from boot: 1days 01:02:03",
        "show status dhcp": "",
        "show arp": "",
        "show status switching-hub macaddress": "",
        "show status lan1": "Transmitted: 10 packets (100 octets)\nReceived: 20 packets (200 octets)",
    }
    responses[failed_command] = "Error: Invalid command name"
    monkeypatch.setattr(cli, "collect", lambda *_args: (responses, 0.1))
    failures: list[str] = []

    output = write_metrics(settings, "password", failures)
    contents = output.read_text(encoding="utf-8")
    assert failures == ["ValueError"]
    assert "home_router_probe_success 0.0" in contents
    assert "home_router_table_entries{" not in contents
    assert not (settings.snapshot_directory / "latest.json").exists()


def test_main_returns_one_when_router_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    from pi_router_probe import cli

    settings = Settings(tmp_path / "password", tmp_path, "router.prom", tmp_path / "snapshot", "router", "user", 22, 30, ("lan1",))
    monkeypatch.setattr(cli, "load_settings", lambda _path: settings)
    monkeypatch.setattr(cli, "load_password", lambda _path: "password")

    def fail(*_args: object) -> tuple[dict[str, str], float]:
        raise RuntimeError("router SSH session is not connected")

    monkeypatch.setattr(cli, "collect", fail)
    assert cli.main(["--config", "unused"]) == 1

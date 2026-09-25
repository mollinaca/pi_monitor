from pathlib import Path

import pytest

from pi_router_probe.cli import clean_cli_output, count_table_rows, load_settings, parse_environment, parse_lan_counters


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

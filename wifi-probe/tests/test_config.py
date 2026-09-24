from pathlib import Path

import pytest

from pi_wifi_probe.config import ConfigError, load_config


BASE_CONFIG = """
[probe]
interface = "wlan0"
management_interface = "eth0"
country = "JP"
gateway = "192.168.100.1"
internet_target = "1.1.1.1"
ping_count = 5
ping_timeout_seconds = 2
connect_timeout_seconds = 30
route_table = 201
route_rule_priority = 20100
metrics_directory = "/tmp/metrics"
state_path = "/tmp/state.json"
lock_path = "/tmp/probe.lock"

[[targets]]
id = "ap1_24"
ap = "AP-1F"
band = "2.4GHz"
connection = "pi-monitor-ap1-24"
"""


def test_load_config(tmp_path: Path) -> None:
    path = tmp_path / "probes.toml"
    path.write_text(BASE_CONFIG, encoding="utf-8")
    config = load_config(path)
    assert config.settings.interface == "wlan0"
    assert config.targets[0].id == "ap1_24"


@pytest.mark.parametrize("key", ["ssid", "bssid", "password", "psk"])
def test_rejects_private_wifi_values(tmp_path: Path, key: str) -> None:
    path = tmp_path / "probes.toml"
    path.write_text(BASE_CONFIG + f'\n{key} = "must-not-be-committed"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="must stay in NetworkManager"):
        load_config(path)

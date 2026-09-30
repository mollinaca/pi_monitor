from pathlib import Path

import pytest

from pi_wifi_probe.model import Settings
from pi_wifi_probe.probe import CommandResult, ProbeError, WifiProbe


def settings(tmp_path: Path) -> Settings:
    return Settings(
        interface="wlan0",
        management_interface="eth0",
        country="JP",
        gateway="192.0.2.1",
        internet_target="1.1.1.1",
        ping_count=1,
        ping_timeout_seconds=1,
        connect_timeout_seconds=1,
        route_table=201,
        route_rule_priority=20100,
        metrics_directory=tmp_path,
        state_path=tmp_path / "state.json",
        lock_path=tmp_path / "lock",
    )


class FakeRunner:
    def __init__(self, *, state: str = "30 (disconnected)", rules: str = "[]", fail_routes: bool = False):
        self.state = state
        self.rules = rules
        self.fail_routes = fail_routes
        self.calls: list[tuple[str, ...]] = []

    def run(self, arguments: list[str], *, timeout: int = 15, check: bool = True) -> CommandResult:
        command = tuple(arguments)
        self.calls.append(command)
        if command == ("ip", "rule", "del", "table", "201"):
            if self.fail_routes:
                raise RuntimeError("ip failed")
            return CommandResult(2, "", "")
        if command == ("ip", "route", "flush", "table", "201"):
            return CommandResult(0, "", "")
        if command == ("ip", "-j", "-4", "rule", "show"):
            return CommandResult(0, self.rules, "")
        if command == ("ip", "-j", "-4", "route", "show", "table", "201"):
            return CommandResult(0, "[]", "")
        if command == ("nmcli", "connection", "down", "test-profile"):
            return CommandResult(10, "", "")
        if command == ("nmcli", "-g", "GENERAL.STATE", "device", "show", "wlan0"):
            return CommandResult(0, self.state, "")
        if command == ("ip", "route", "show", "default"):
            return CommandResult(0, "default via 192.0.2.1 dev eth0 metric 100", "")
        raise AssertionError(f"unexpected command: {command}")


def test_cleanup_reports_connection_that_remains_active(tmp_path: Path) -> None:
    runner = FakeRunner(state="100 (connected)")
    probe = WifiProbe(settings(tmp_path), runner)
    probe._active_connection = "test-profile"

    with pytest.raises(ProbeError, match="Wi-Fi remains active"):
        probe.cleanup()


def test_cleanup_accepts_disconnect_error_when_already_disconnected(tmp_path: Path) -> None:
    runner = FakeRunner()
    probe = WifiProbe(settings(tmp_path), runner)
    probe._active_connection = "test-profile"

    probe.cleanup()


def test_cleanup_attempts_disconnect_after_route_failure(tmp_path: Path) -> None:
    runner = FakeRunner(fail_routes=True)
    probe = WifiProbe(settings(tmp_path), runner)
    probe._active_connection = "test-profile"

    with pytest.raises(ProbeError, match="probe routes"):
        probe.cleanup()
    assert ("nmcli", "connection", "down", "test-profile") in runner.calls


def test_cleanup_reports_residual_policy_rule(tmp_path: Path) -> None:
    runner = FakeRunner(rules='[{"priority":20100,"src":"192.0.2.3","table":"201"}]')
    probe = WifiProbe(settings(tmp_path), runner)
    probe._active_connection = "test-profile"

    with pytest.raises(ProbeError, match="probe routes"):
        probe.cleanup()

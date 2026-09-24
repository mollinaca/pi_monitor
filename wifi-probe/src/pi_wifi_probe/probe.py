from __future__ import annotations

import ipaddress
import os
import shutil
import subprocess
import time
from dataclasses import dataclass

from .model import ProbeResult, Settings, Target
from .parsers import parse_link, parse_ping


class ProbeError(RuntimeError):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    def run(
        self,
        arguments: list[str],
        *,
        timeout: int = 15,
        check: bool = True,
    ) -> CommandResult:
        environment = os.environ.copy()
        environment["LC_ALL"] = "C"
        try:
            completed = subprocess.run(
                arguments,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=environment,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"command failed: {arguments[0]}") from exc
        result = CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"command returned {result.returncode}: {arguments[0]}")
        return result


def check_prerequisites(settings: Settings, targets: tuple[Target, ...]) -> None:
    missing = [
        command
        for command in ("ip", "iw", "nmcli", "ping")
        if shutil.which(command) is None
    ]
    if missing:
        raise ProbeError("preflight", f"missing commands: {', '.join(missing)}")

    runner = CommandRunner()
    default_routes = runner.run(["ip", "route", "show", "default"]).stdout
    if f" dev {settings.management_interface} " not in f" {default_routes.strip()} ":
        raise ProbeError(
            "preflight",
            f"default route is not using {settings.management_interface}",
        )
    for target in targets:
        autoconnect = runner.run(
            [
                "nmcli",
                "-g",
                "connection.autoconnect",
                "connection",
                "show",
                target.connection,
            ],
            check=False,
        )
        if autoconnect.returncode != 0:
            raise ProbeError(
                "preflight", f"NetworkManager profile is missing for {target.id}"
            )
        if autoconnect.stdout.strip().lower() != "no":
            raise ProbeError(
                "preflight", f"NetworkManager autoconnect must be disabled for {target.id}"
            )
        pinned_bssid = runner.run(
            [
                "nmcli",
                "-g",
                "802-11-wireless.bssid",
                "connection",
                "show",
                target.connection,
            ],
            check=False,
        )
        if pinned_bssid.returncode != 0 or not pinned_bssid.stdout.strip():
            raise ProbeError(
                "preflight", f"NetworkManager profile must pin a BSSID for {target.id}"
            )


class WifiProbe:
    def __init__(self, settings: Settings, runner: CommandRunner | None = None):
        self.settings = settings
        self.runner = runner or CommandRunner()
        self._radio_was_enabled = False
        self._radio_state_known = False
        self._route_installed = False
        self._active_connection: str | None = None

    def _radio_enabled(self) -> bool:
        output = self.runner.run(["nmcli", "radio", "wifi"]).stdout.strip().lower()
        return output == "enabled"

    def _assert_management_route(self) -> None:
        routes = self.runner.run(["ip", "route", "show", "default"]).stdout
        if f" dev {self.settings.management_interface} " not in f" {routes.strip()} ":
            raise ProbeError("preflight", "management default route changed unexpectedly")

    def _cleanup_routes(self) -> None:
        while True:
            deleted = self.runner.run(
                ["ip", "rule", "del", "table", str(self.settings.route_table)],
                check=False,
            )
            if deleted.returncode != 0:
                break
        self.runner.run(
            ["ip", "route", "flush", "table", str(self.settings.route_table)],
            check=False,
        )
        self._route_installed = False

    def _install_routes(self, address_with_prefix: str) -> str:
        interface = ipaddress.ip_interface(address_with_prefix)
        source = str(interface.ip)
        self._cleanup_routes()
        self._route_installed = True
        self.runner.run(
            [
                "ip",
                "route",
                "add",
                "table",
                str(self.settings.route_table),
                str(interface.network),
                "dev",
                self.settings.interface,
                "src",
                source,
            ]
        )
        self.runner.run(
            [
                "ip",
                "route",
                "add",
                "table",
                str(self.settings.route_table),
                "default",
                "via",
                self.settings.gateway,
                "dev",
                self.settings.interface,
            ]
        )
        self.runner.run(
            [
                "ip",
                "rule",
                "add",
                "priority",
                str(self.settings.route_rule_priority),
                "from",
                f"{source}/32",
                "table",
                str(self.settings.route_table),
            ]
        )
        return source

    def _address(self) -> str:
        output = self.runner.run(
            [
                "ip",
                "-4",
                "-o",
                "address",
                "show",
                "dev",
                self.settings.interface,
                "scope",
                "global",
            ]
        ).stdout
        for token in output.split():
            if "/" in token:
                try:
                    ipaddress.ip_interface(token)
                except ValueError:
                    continue
                return token
        raise ProbeError("association", "Wi-Fi interface did not receive an IPv4 address")

    def _ping(self, source: str, destination: str):
        completed = self.runner.run(
            [
                "ping",
                "-I",
                source,
                "-c",
                str(self.settings.ping_count),
                "-W",
                str(self.settings.ping_timeout_seconds),
                destination,
            ],
            timeout=(
                self.settings.ping_count * self.settings.ping_timeout_seconds + 10
            ),
            check=False,
        )
        try:
            return parse_ping(completed.stdout + completed.stderr)
        except ValueError as exc:
            raise ProbeError("ping", "could not parse ping result") from exc

    def run(self, target: Target) -> ProbeResult:
        started_wall = time.time()
        started = time.monotonic()
        result = ProbeResult(target=target, timestamp=started_wall)
        try:
            self._assert_management_route()
            self._radio_was_enabled = self._radio_enabled()
            self._radio_state_known = True
            self.runner.run(["iw", "reg", "set", self.settings.country])
            if not self._radio_was_enabled:
                self.runner.run(["nmcli", "radio", "wifi", "on"])

            association_started = time.monotonic()
            try:
                self.runner.run(
                    [
                        "nmcli",
                        "--wait",
                        str(self.settings.connect_timeout_seconds),
                        "connection",
                        "up",
                        target.connection,
                        "ifname",
                        self.settings.interface,
                    ],
                    timeout=self.settings.connect_timeout_seconds + 5,
                )
            except RuntimeError as exc:
                raise ProbeError("association", "Wi-Fi association failed") from exc
            self._active_connection = target.connection
            result.association_duration_seconds = time.monotonic() - association_started
            result.association_success = True

            source = self._install_routes(self._address())
            gateway = self._ping(source, self.settings.gateway)
            result.gateway_packet_loss_ratio = gateway.packet_loss_ratio
            result.gateway_latency_seconds = gateway.average_seconds
            result.gateway_ping_success = gateway.packet_loss_ratio == 0

            internet = self._ping(source, self.settings.internet_target)
            result.internet_packet_loss_ratio = internet.packet_loss_ratio
            result.internet_latency_seconds = internet.average_seconds
            result.internet_ping_success = internet.packet_loss_ratio == 0

            link_output = self.runner.run(
                ["iw", "dev", self.settings.interface, "link"]
            ).stdout
            station_output = self.runner.run(
                ["iw", "dev", self.settings.interface, "station", "dump"]
            ).stdout
            link = parse_link(link_output, station_output)
            result.signal_dbm = link.signal_dbm
            result.frequency_mhz = link.frequency_mhz
            result.channel = link.channel
            result.rx_bitrate_mbps = link.rx_bitrate_mbps
            result.tx_bitrate_mbps = link.tx_bitrate_mbps
            result.tx_failed_packets = link.tx_failed_packets

            result.success = (
                result.association_success
                and result.gateway_ping_success
                and result.internet_ping_success
            )
            result.failed_stage = "none" if result.success else "connectivity"
        except ProbeError as exc:
            result.failed_stage = exc.stage
        except RuntimeError:
            result.failed_stage = "command"
        finally:
            result.duration_seconds = time.monotonic() - started
            try:
                self.cleanup()
            except (ProbeError, RuntimeError):
                result.success = False
                result.failed_stage = "cleanup"
        return result

    def cleanup(self) -> None:
        if self._route_installed:
            self._cleanup_routes()
        if self._active_connection is not None:
            self.runner.run(
                ["nmcli", "connection", "down", self._active_connection],
                check=False,
            )
            self._active_connection = None
        else:
            self.runner.run(
                ["nmcli", "device", "disconnect", self.settings.interface],
                check=False,
            )
        if self._radio_state_known and not self._radio_was_enabled:
            self.runner.run(["nmcli", "radio", "wifi", "off"], check=False)
        self._assert_management_route()

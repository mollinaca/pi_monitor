from __future__ import annotations

import argparse
import fcntl
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import ConfigError, load_config
from .metrics import write_metrics
from .model import Config, ProbeResult, Target
from .probe import ProbeError, WifiProbe, check_prerequisites
from .state import ProbeState, load_state, save_state


DEFAULT_CONFIG = Path("/mnt/data/pi_monitor/wifi-probe/config/probes.toml")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure one or more configured Wi-Fi paths"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"configuration file (default: {DEFAULT_CONFIG})",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--target", help="measure one target by its stable ID")
    selection.add_argument(
        "--all", action="store_true", help="measure every target in configuration order"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate configuration, commands, routes, and NetworkManager profiles",
    )
    return parser


@contextmanager
def process_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another Wi-Fi probe is already running") from exc
        lock.write(f"{Path('/proc/self').resolve().name}\n")
        lock.flush()
        yield


def _find_target(config: Config, target_id: str) -> Target:
    for target in config.targets:
        if target.id == target_id:
            return target
    raise ConfigError(f"unknown target: {target_id}")


def _select_targets(
    config: Config, state: ProbeState, target_id: str | None, all_targets: bool
) -> tuple[tuple[Target, ...], bool]:
    if target_id is not None:
        return (_find_target(config, target_id),), False
    if all_targets:
        return config.targets, False
    index = state.next_index % len(config.targets)
    return (config.targets[index],), True


def _summary(result: ProbeResult, metrics_path: Path) -> str:
    status = "SUCCESS" if result.success else "FAILED"
    values = [
        f"{result.target.ap} {result.target.band}",
        status,
        f"stage={result.failed_stage}",
    ]
    if result.signal_dbm is not None:
        values.append(f"signal={result.signal_dbm:.0f}dBm")
    if result.channel is not None:
        values.append(f"channel={result.channel}")
    if result.tx_bitrate_mbps is not None:
        values.append(f"tx={result.tx_bitrate_mbps:g}Mbit/s")
    if result.gateway_latency_seconds is not None:
        values.append(f"gateway={result.gateway_latency_seconds * 1000:.2f}ms")
    if result.internet_latency_seconds is not None:
        values.append(f"internet={result.internet_latency_seconds * 1000:.2f}ms")
    values.append(f"metrics={metrics_path}")
    return " | ".join(values)


def run(arguments: list[str] | None = None) -> int:
    args = build_parser().parse_args(arguments)
    try:
        config = load_config(args.config)
        selected_for_validation = (
            (_find_target(config, args.target),) if args.target else config.targets
        )
        check_prerequisites(config.settings, selected_for_validation)
        if args.dry_run:
            print(
                f"configuration valid: {len(config.targets)} targets; "
                f"validated {len(selected_for_validation)} NetworkManager profiles"
            )
            return 0

        if os.geteuid() != 0:
            raise RuntimeError("measurement must be run as root")

        if not hasattr(fcntl, "flock"):
            raise RuntimeError("file locking is not available on this platform")
        with process_lock(config.settings.lock_path):
            state = load_state(config.settings.state_path)
            targets, advance_rotation = _select_targets(
                config, state, args.target, args.all
            )
            failed = False
            for target in targets:
                result = WifiProbe(config.settings).run(target)
                if result.success:
                    state.last_success[target.id] = result.timestamp
                last_success = state.last_success.get(target.id, 0.0)
                metrics_path = write_metrics(
                    result, config.settings.metrics_directory, last_success
                )
                print(_summary(result, metrics_path))
                failed = failed or not result.success
            if advance_rotation:
                state.next_index = (state.next_index + 1) % len(config.targets)
            save_state(config.settings.state_path, state)
            return 1 if failed else 0
    except (ConfigError, ProbeError, RuntimeError, OSError) as exc:
        print(f"pi-wifi-probe: {exc}", file=sys.stderr)
        return 2


def main() -> None:
    raise SystemExit(run())

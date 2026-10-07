#!/usr/bin/env python3
"""Export Raspberry Pi firmware throttling flags to node_exporter textfile."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


FLAGS = (
    ("undervoltage", 0),
    ("frequency_capped", 1),
    ("throttled", 2),
    ("soft_temperature_limit", 3),
)


def parse_throttled(output: str) -> int:
    match = re.fullmatch(r"throttled=(0x[0-9a-fA-F]+)\s*", output)
    if match is None:
        raise ValueError(f"Unexpected vcgencmd output: {output!r}")
    return int(match.group(1), 16)


def render_metrics(bits: int | None, timestamp: int) -> str:
    lines = [
        "# HELP home_pi_throttling_probe_success Whether vcgencmd get_throttled succeeded.",
        "# TYPE home_pi_throttling_probe_success gauge",
        f"home_pi_throttling_probe_success {int(bits is not None)}",
        "# HELP home_pi_throttling_probe_timestamp_seconds Unix time of the last probe attempt.",
        "# TYPE home_pi_throttling_probe_timestamp_seconds gauge",
        f"home_pi_throttling_probe_timestamp_seconds {timestamp}",
        "# HELP home_pi_throttling_state Firmware undervoltage and throttling flags; since_boot flags are latched until reboot.",
        "# TYPE home_pi_throttling_state gauge",
    ]
    if bits is not None:
        for scope, offset in (("current", 0), ("since_boot", 16)):
            for condition, bit in FLAGS:
                lines.append(
                    f'home_pi_throttling_state{{condition="{condition}",scope="{scope}"}} '
                    f"{int(bool(bits & (1 << (bit + offset))))}"
                )
    return "\n".join(lines) + "\n"


def write_atomic(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=f".{path.name}.", delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
            os.chmod(temporary, 0o644)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = subprocess.run(["vcgencmd", "get_throttled"], check=True, capture_output=True, text=True, timeout=10)
        bits = parse_throttled(result.stdout)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        write_atomic(args.output, render_metrics(None, int(time.time())))
        raise
    write_atomic(args.output, render_metrics(bits, int(time.time())))


if __name__ == "__main__":
    main()

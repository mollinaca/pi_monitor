from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProbeState:
    next_index: int = 0
    last_success: dict[str, float] = field(default_factory=dict)


def load_state(path: Path) -> ProbeState:
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ProbeState()
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return ProbeState()
    if not isinstance(raw, dict):
        return ProbeState()
    next_index = raw.get("next_index", 0)
    raw_success = raw.get("last_success", {})
    if not isinstance(next_index, int) or next_index < 0:
        next_index = 0
    last_success: dict[str, float] = {}
    if isinstance(raw_success, dict):
        for key, value in raw_success.items():
            if isinstance(key, str) and isinstance(value, (int, float)):
                last_success[key] = float(value)
    return ProbeState(next_index=next_index, last_success=last_success)


def save_state(path: Path, state: ProbeState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = {
        "next_index": state.next_index,
        "last_success": state.last_success,
    }
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

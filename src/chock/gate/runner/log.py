"""Gate runner: the best-effort gate event log."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from .constants import (
    _CONFIG_PATH,
    _EVENT_NAME,
    _LOG_MATCH_CAP,
    _LOG_MAX_BYTES,
    _MIN_COMPILED_PATH_DEPTH,
    ACTION_BLOCK,
    GATE_LOG_ENV,
)
from .context import GateResult


# >>> gate.py 10
def _write_log(chock_root: Path, record: dict) -> None:
    """Append one record to `<chock_root>/log/gate-events.jsonl`, rotating past the size cap."""
    log_dir = chock_root / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "gate-events.jsonl"
    if log_path.exists() and log_path.stat().st_size > _LOG_MAX_BYTES:
        log_path.replace(log_dir / "gate-events.1.jsonl")
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps({"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **record}, ensure_ascii=False)
            + "\n"
        )


def _log_outcome(
    gate_path: Path,
    event: str,
    spec: dict,
    result: GateResult,
    verdict: str,
    extra: Mapping[str, object] | None = None,
) -> None:
    """Append one outcome record. Best effort: never raises, never changes the verdict."""
    try:
        if os.environ.get(GATE_LOG_ENV) == "0" and not _held(extra):
            return
        parents = gate_path.resolve().parents
        if len(parents) < _MIN_COMPILED_PATH_DEPTH or parents[2].name != "compiled":
            return
        record = {
            "policy_id": parents[1].name,
            "surface": parents[0].name,
            "event": event,
            "kind": spec.get("kind"),
            "verdict": verdict,
            "match_count": len(result.matches),
            "matches": result.matches[:_LOG_MATCH_CAP],
            **result.detail,
        }
        if result.rules:
            record["rules"] = result.rules
        record.update(extra or {})
        _write_log(parents[3], record)
    except Exception:  # noqa: BLE001 -- best effort logging: never raises, never changes the verdict
        return


# >>> gate.py 18
def _held(extra: Mapping[str, object] | None) -> bool:
    """A record of what the rollout level let through: the evidence for enforcing, so it is written
    even when `CHOCK_GATE_LOG=0` turns the rest of the log off."""
    return bool(extra and "would_action" in extra)


def _actor(signal: str | None) -> dict[str, object]:
    """The agent marker a log record carries, when an agent acted."""
    return {"agent": signal} if signal else {}


def _held_record(held: str, level: str) -> dict[str, object]:
    """What the log keeps of an action the rollout level lowered: the evidence for switching to enforce."""
    return {"rollout": level, "would_action": held, "would_block": held == ACTION_BLOCK}


def _log_script_hook(
    policy_id: str, event: str, verdict: str, repo_root: Path, extra: Mapping[str, object] | None = None
) -> None:
    """Record a script-backed hook's warn or ask; best effort like every gate log write."""
    try:
        if os.environ.get(GATE_LOG_ENV) == "0" and not _held(extra):
            return
        record = {"policy_id": policy_id, "surface": "git-hook", "event": _EVENT_NAME.get(event, event)}
        record.update({"kind": "script-hook", "verdict": verdict, "match_count": 0, "matches": []})
        record.update(extra or {})
        _write_log(repo_root / _CONFIG_PATH[0], record)
    except Exception:  # noqa: BLE001 -- best effort logging: never raises, never changes the verdict
        return

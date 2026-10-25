"""The toggle wrapper's log line and HEAD lookup. Stdlib only: shipped beside the wrapper in every merged plugin."""

from __future__ import annotations

import subprocess
from pathlib import Path

try:  # beside the wrapper in a merged plugin; inside the chock package everywhere else
    from chock_journal import LOG_INFO, LOG_OFF, log_append, log_settings
except ImportError:
    from chock.gate.runner.journal import LOG_INFO, LOG_OFF, log_append, log_settings

_LOG_PARTS = ("log", "gate-events.jsonl")
_GIT_SECONDS = 5


def head_text(root: Path, name: str) -> str | None:
    """`name` as HEAD of the repository at `root` holds it; None when HEAD has no such file or git fails."""
    argv = ["git", "-C", str(root), "show", f"HEAD:{name}"]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=_GIT_SECONDS, check=False)  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def vouched(toggles: dict[str, dict[str, str]], head: dict[str, dict[str, str]]) -> tuple[dict, list[str]]:
    """(`toggles` keeping only the offs `head` also has, the `bundle/member` offs it dropped)."""
    dropped = [
        f"{b}/{m}" for b, ms in toggles.items() for m, s in ms.items() if s == "off" and head.get(b, {}).get(m) != "off"
    ]
    return {b: {m: s for m, s in ms.items() if f"{b}/{m}" not in dropped} for b, ms in toggles.items()}, dropped


def _repo(start: Path) -> Path | None:
    here = Path(start).absolute()
    return next((folder for folder in (here, *here.parents) if (folder / ".git").exists()), None)


def log_off(governing: Path, bundle: str, member: str) -> None:
    """One info line in chock's log beside the governing file, unless the level is off. Best effort: never raises."""
    try:
        level, size = log_settings(_repo(Path.cwd()))
        if level == LOG_OFF:
            return
        record = {"route": "plugin", "level": LOG_INFO, "policy_id": member, "surface": "plugin", "event": "toggle"}
        record |= {"kind": "guardrails-off", "bundle": bundle, "verdict": "off"}
        log_append(governing.parent.joinpath(*_LOG_PARTS), record, size)
    except Exception:  # noqa: BLE001 -- a log line must never change the verdict
        return

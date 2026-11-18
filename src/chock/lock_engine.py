"""chock.lock's `engine` constraint: derived from the running engine, checked against it (IR-F71)."""

from __future__ import annotations

import re
from typing import Any

from chock import __version__

LOCKFILE_NAME = "chock.lock"
#: What every lock said before the field was read; such a lock passes with a note to re-lock.
LEGACY_ENGINE_CONSTRAINT = ">=0.1,<0.2"
_VERSION_PREFIX = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")
_CONSTRAINT_RE = re.compile(r"\s*>=\s*(\d+(?:\.\d+){0,2})\s*,\s*<\s*(\d+(?:\.\d+){0,2})\s*")


def _version_tuple(version: str) -> tuple[int, int, int] | None:
    """(major, minor, patch) from the leading digits of a version string; None when it has none."""
    match = _VERSION_PREFIX.match(version.strip())
    if not match:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def _padded(dotted: str) -> tuple[int, int, int]:
    """A constraint bound as (major, minor, patch), missing parts 0."""
    major, minor, patch, *_ = [*(int(p) for p in dotted.split(".")), 0, 0]
    return major, minor, patch


def engine_constraint(version: str = __version__) -> str:
    """The constraint a lock written by engine `version` carries: `>=<major>.<minor>,<<major+1>`."""
    parsed = _version_tuple(version)
    if parsed is None:
        msg = f"engine version {version!r} has no <major>.<minor> prefix"
        raise ValueError(msg)
    major, minor, _patch = parsed
    return f">={major}.{minor},<{major + 1}"


def check_engine(constraint: object, version: str = __version__) -> tuple[str | None, str | None]:
    """(failure, note) for the running engine against a lock's `engine` field; both None when it satisfies it."""
    relock = "or run `chock sync --repo .` with the newer engine to re-lock"
    if constraint == LEGACY_ENGINE_CONSTRAINT:
        return None, (
            f"note: {LOCKFILE_NAME} engine constraint {constraint!r} was written before constraints were read; "
            "run `chock sync --repo .` to record this engine's constraint"
        )
    match = _CONSTRAINT_RE.fullmatch(constraint) if isinstance(constraint, str) else None
    running = _version_tuple(version)
    if match is None or running is None:
        what = f"engine {version}" if running is None else f"{LOCKFILE_NAME} engine constraint {constraint!r}"
        return f"{what} cannot be read; expected `>=X.Y,<Z` -- `pip install` a matching chock {relock}", None
    low, high = _padded(match.group(1)), _padded(match.group(2))
    if low <= running < high:
        return None, None
    return (
        f"engine {version} is outside {LOCKFILE_NAME}'s constraint {constraint!r} -- "
        f'`pip install "chock{constraint}"`, {relock}'
    ), None


def engine_failures(lock: dict[str, Any], notes: list[str] | None) -> list[str]:
    """`check_engine` on a lock: its failure as a list, its note appended to `notes` when given."""
    failure, note = check_engine(lock.get("engine"))
    if note and notes is not None:
        notes.append(note)
    return [failure] if failure else []

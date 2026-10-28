"""Shared helpers for tests that compare built package trees."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from chock.plugin import hook_dir


def tree_bytes(root: Path) -> dict[str, bytes]:
    """Every file under `root`, by relative path, as bytes."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def frozen_json(path: Path, found: object) -> object:
    """The golden at `path`; with CHOCK_REGEN_GOLDENS=1, `found` is written there first and the test skips."""
    if os.environ.get("CHOCK_REGEN_GOLDENS") == "1":
        path.write_text(json.dumps(found, indent=2) + "\n", encoding="utf-8")
        pytest.skip(f"{path.name} regenerated -- commit the diff")
    return json.loads(path.read_text(encoding="utf-8"))


def golden_posix(monkeypatch: pytest.MonkeyPatch, path: Path, build) -> None:
    """Compare `build()` with the golden at `path`, always in the POSIX form (also under CHOCK_REGEN_GOLDENS=1)."""
    monkeypatch.setattr(hook_dir, "build_windows", lambda: False)
    found = build()
    assert found == frozen_json(path, found)

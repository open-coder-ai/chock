"""Workflows build and editable-install with the hash-pinned backend, never an isolated fetch."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
REQ = ROOT / "requirements"
EDITABLE = re.compile(r"\bpip install\b.*\s-e\s")
BUILD = re.compile(r"\bpython -m build\b")
PINNED_BACKEND = re.compile(r"^setuptools==([0-9][^\s\\]*)", re.MULTILINE)
REQ_FILE = re.compile(r"-r requirements/([\w.-]+\.txt)")


def _commands(job: dict) -> list[str]:
    runs = [s["run"] for s in job.get("steps", []) if "run" in s]
    return [c.strip() for run in runs for line in run.splitlines() for c in line.split("&&")]


def _jobs() -> list[tuple[str, str, dict]]:
    return [
        (path.name, name, job)
        for path in WORKFLOWS
        for name, job in yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"].items()
    ]


def _backend(name: str) -> str | None:
    found = PINNED_BACKEND.search((REQ / name).read_text(encoding="utf-8"))
    return found.group(1) if found else None


@pytest.mark.parametrize(("wf", "job", "spec"), _jobs(), ids=lambda v: v if isinstance(v, str) else "")
def test_no_isolated_build_or_editable_install(wf: str, job: str, spec: dict) -> None:
    for cmd in _commands(spec):
        if EDITABLE.search(cmd):
            assert "--no-build-isolation" in cmd, f"{wf}:{job}: {cmd}"
            assert "--no-deps" in cmd, f"{wf}:{job}: {cmd}"
        if BUILD.search(cmd):
            assert "--no-isolation" in cmd, f"{wf}:{job}: {cmd}"


@pytest.mark.parametrize(("wf", "job", "spec"), _jobs(), ids=lambda v: v if isinstance(v, str) else "")
def test_unisolated_jobs_install_the_pinned_backend(wf: str, job: str, spec: dict) -> None:
    cmds = _commands(spec)
    if not any(EDITABLE.search(c) or BUILD.search(c) for c in cmds):
        return
    installed = {f for c in cmds if "--require-hashes" in c for f in REQ_FILE.findall(c)}
    assert any(_backend(f) for f in installed), f"{wf}:{job}: no hash-pinned setuptools in {sorted(installed)}"


def test_build_lock_pins_the_backend_the_dev_lock_uses() -> None:
    pinned = _backend("build.txt")
    assert pinned is not None
    assert pinned == _backend("dev.txt")
    block = (REQ / "build.txt").read_text(encoding="utf-8").split(f"setuptools=={pinned}", 1)[1]
    assert "--hash=sha256:" in block.split("# via", 1)[0]

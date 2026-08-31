"""Shared test helpers for gate and runner tests."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]

REPO_POLICIES = FRAMEWORK_ROOT / ".agents" / "policies"


@pytest.fixture(autouse=True)
def no_gate_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite out of this repo's own gate outcome log."""
    monkeypatch.setenv("CHOCK_GATE_LOG", "0")


def baseline_policy(policy_id: str) -> Path:
    """Directory of one of this repo's own baseline-derived policies."""
    path = REPO_POLICIES / policy_id
    assert path.is_dir(), f"no policy named {policy_id!r} under .agents/policies/"
    return path


def init_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    return tmp_path


def stage(tmp_path: Path, rel: str, content: str) -> None:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", rel], cwd=tmp_path, check=True)


def write_gate(tmp_path: Path, spec: dict) -> Path:
    gate = tmp_path / "gate.json"
    gate.write_text(json.dumps(spec), encoding="utf-8")
    return gate


def build_test_gate_json(tmp_path: Path, policy_dir: Path) -> Path:
    """Build a flat, resolved gate.json from a policy's manifest hook.gate for tests."""
    from chock.gate.build import build_gate_json

    spec = build_gate_json(policy_dir, tmp_path)
    assert spec is not None, f"No hook.gate found in {policy_dir}"
    gate_path = tmp_path / "gate.json"
    gate_path.write_text(json.dumps(spec), encoding="utf-8")
    return gate_path


@pytest.fixture(scope="session")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One wheel per test session, built from a clean copy of the tree."""
    pytest.importorskip("build")
    src = tmp_path_factory.mktemp("wheelsrc") / "chock"
    shutil.copytree(
        FRAMEWORK_ROOT,
        src,
        ignore=shutil.ignore_patterns(
            "build", "dist", "*.egg-info", ".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache"
        ),
    )
    out = tmp_path_factory.mktemp("wheeldist")
    proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "-o", str(out)], cwd=src, capture_output=True, text=True
    )
    assert proc.returncode == 0, f"wheel build failed:\n{proc.stdout}\n{proc.stderr}"
    wheels = list(out.glob("*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


def working_bash() -> str | None:
    """A bash that actually runs, or None."""
    candidates = []
    if path_bash := shutil.which("bash"):
        candidates.append(path_bash)
    if git := shutil.which("git"):
        git_bash = Path(git).resolve().parent.parent / "bin" / "bash.exe"
        if git_bash.exists():
            candidates.append(str(git_bash))
    for candidate in candidates:
        try:
            proc = subprocess.run([candidate, "-c", "echo ok"], capture_output=True, text=True, timeout=10)
        except OSError:
            continue
        if proc.returncode == 0 and proc.stdout.strip() == "ok":
            return candidate
    return None


WORKING_BASH = working_bash()

needs_bash = pytest.mark.skipif(WORKING_BASH is None, reason="no working bash on this machine")

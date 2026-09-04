"""Behavioural tests for the test-integrity gate: green CI must be earned, not arranged."""

from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import baseline_policy, build_test_gate_json, init_repo, stage

from chock.gate.runner import run

POLICY_DIR = baseline_policy("test-integrity")

REAL_TEST = """def test_adds():
    assert add(1, 2) == 3
    assert add(0, 0) == 0
"""


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    init_repo(tmp_path)
    stage(tmp_path, "tests/test_math.py", REAL_TEST)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    return tmp_path, build_test_gate_json(tmp_path, POLICY_DIR)


def _verdict(repo: Path, gate: Path) -> int:
    return run(gate, "pre-commit", None, repo)


def test_a_real_fix_passes(tmp_path: Path) -> None:
    repo, gate = _repo(tmp_path)
    stage(repo, "app.py", "def add(a, b):\n    return a + b\n")
    assert _verdict(repo, gate) == 0


def test_adding_assertions_passes(tmp_path: Path) -> None:
    repo, gate = _repo(tmp_path)
    stage(repo, "tests/test_math.py", REAL_TEST + "    assert add(-1, 1) == 0\n")
    assert _verdict(repo, gate) == 0


def test_deleting_a_test_file_is_blocked(tmp_path: Path) -> None:
    repo, gate = _repo(tmp_path)
    subprocess.run(["git", "rm", "-q", "tests/test_math.py"], cwd=repo, check=True)
    assert _verdict(repo, gate) != 0


def test_stripping_assertions_is_blocked(tmp_path: Path) -> None:
    """The actual attack: keep the test, remove what it checks, collect green CI."""
    repo, gate = _repo(tmp_path)
    stage(repo, "tests/test_math.py", "def test_adds():\n    add(1, 2)\n")
    assert _verdict(repo, gate) != 0


def test_a_vacuous_assertion_is_blocked(tmp_path: Path) -> None:
    repo, gate = _repo(tmp_path)
    stage(repo, "tests/test_math.py", REAL_TEST + "\n\ndef test_new():\n    assert True\n")
    assert _verdict(repo, gate) != 0


def test_non_test_paths_are_not_policed(tmp_path: Path) -> None:
    """Deleting an assert from application code is a refactor, not test tampering."""
    repo, gate = _repo(tmp_path)
    stage(repo, "app.py", "def add(a, b):\n    assert isinstance(a, int)\n    return a + b\n")
    subprocess.run(["git", "commit", "-qm", "app"], cwd=repo, check=True)
    stage(repo, "app.py", "def add(a, b):\n    return a + b\n")
    assert _verdict(repo, gate) == 0


def test_a_spec_directory_of_prose_is_not_policed(tmp_path: Path) -> None:
    """A `spec/` directory of design docs (this repo's own layout) is not RSpec test code."""
    repo, gate = _repo(tmp_path)
    stage(repo, "spec/gate-dsl.md", "docs describing `assert True` as an example of a vacuous check\n")
    assert _verdict(repo, gate) == 0


def test_a_reviewed_removal_is_allowed_through(tmp_path: Path) -> None:
    """The escape hatch is deliberate, in the diff, and named — not a config toggle."""
    repo, gate = _repo(tmp_path)
    stage(repo, "tests/test_math.py", "def test_adds():  # chock: test-removal-reviewed\n    assert add(1, 2) == 3\n")
    assert _verdict(repo, gate) == 0

"""test_integrity honours its waiver at agent events only when HEAD already carries the line."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import baseline_policy, build_test_gate_json, init_repo, stage

from chock.gate.runner import AGENT_COMMIT_ENV, run

PRAGMA = "  # chock: test-removal-reviewed"
HEAD_TEST = f"def test_a():\n    assert legacy(){PRAGMA}\n    assert one() == 1\n"
DROPPED = "def test_a():\n    assert one() == 1\n"
STRIPPED = "def test_a():\n    one()\n"
STRIPPED_WAIVED = f"def test_a():\n    one(){PRAGMA}\n"
PATH = "tests/test_a.py"


@pytest.fixture
def gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv(AGENT_COMMIT_ENV, raising=False)
    init_repo(tmp_path)
    stage(tmp_path, PATH, HEAD_TEST)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    built = build_test_gate_json(tmp_path, baseline_policy("test-integrity"))
    spec = json.loads(built.read_text(encoding="utf-8"))
    built.write_text(json.dumps({**spec, "on": ["commit", "tool_use"]}), encoding="utf-8")
    return built


def _tool_use(gate: Path, repo: Path, text: str) -> int:
    return run(gate, "pre-tool-use", None, repo, writes={PATH: text})


def test_a_waiver_already_in_head_lets_the_agent_drop_that_assertion(gate: Path, tmp_path: Path) -> None:
    assert _tool_use(gate, tmp_path, DROPPED) == 0


def test_a_waiver_the_agent_adds_does_not_count(gate: Path, tmp_path: Path) -> None:
    assert _tool_use(gate, tmp_path, STRIPPED_WAIVED) == 1


def test_an_unwaived_removal_still_blocks(gate: Path, tmp_path: Path) -> None:
    assert _tool_use(gate, tmp_path, STRIPPED) == 1


def test_the_same_holds_at_an_agent_commit(gate: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(AGENT_COMMIT_ENV, "1")
    stage(tmp_path, PATH, DROPPED)
    assert run(gate, "pre-commit", None, tmp_path) == 0
    stage(tmp_path, PATH, STRIPPED_WAIVED)
    assert run(gate, "pre-commit", None, tmp_path) == 1


def test_a_person_still_waives_at_commit(gate: Path, tmp_path: Path) -> None:
    stage(tmp_path, PATH, STRIPPED_WAIVED)
    assert run(gate, "pre-commit", None, tmp_path) == 0

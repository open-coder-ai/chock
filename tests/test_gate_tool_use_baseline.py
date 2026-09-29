"""At tool use a waiver must already be in HEAD, and only what changed is judged.

Pre-tool judges the file as it would be, against the disk it replaces. Stop judges the disk,
which already holds the writes, against HEAD. Neither may scan lines nobody changed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import init_repo, write_gate

from chock.compile.emitters.in_agent import tool_use_gate_spec
from chock.gate.runner import WRITE_PATH_KINDS, run
from chock.validation.checks_gate_shape import _validate_gate
from chock.validation.report import Report

WAIVER = r"chock:\s*allow\s+eval"
WAIVED = "x = eval(a)  # chock: allow eval\n"
BAD = "y = eval(b)\n"
EVENTS = ["pre-tool-use", "stop"]


def _commit(repo: Path, **files: str) -> None:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)


def _regex_gate(tmp_path: Path) -> Path:
    params = {"content_pattern": r"\beval\(", "allowlist_pragma": WAIVER}
    return write_gate(
        tmp_path, {"kind": "content_regex", "on": ["tool_use"], "action": "block", "message": "m", "params": params}
    )


def _run(gate: Path, repo: Path, event: str, text: str, path: str = "app.py") -> int:
    return run(gate, event, None, repo, writes={path: text})


@pytest.mark.parametrize("event", EVENTS)
def test_a_waiver_already_in_head_does_not_block(tmp_path: Path, event: str) -> None:
    repo = init_repo(tmp_path)
    _commit(repo, **{"app.py": WAIVED})
    assert _run(_regex_gate(tmp_path), repo, event, WAIVED + "z = 1\n") == 0


@pytest.mark.parametrize("event", EVENTS)
def test_a_waiver_the_agent_adds_still_blocks(tmp_path: Path, event: str) -> None:
    repo = init_repo(tmp_path)
    _commit(repo, **{"app.py": "z = 1\n"})
    assert _run(_regex_gate(tmp_path), repo, event, "z = 1\n" + WAIVED) == 1


@pytest.mark.parametrize("event", EVENTS)
def test_waiving_a_line_already_in_head_unwaived_still_blocks(tmp_path: Path, event: str) -> None:
    repo = init_repo(tmp_path)
    _commit(repo, **{"app.py": "x = eval(a)\n"})
    assert _run(_regex_gate(tmp_path), repo, event, WAIVED) == 1


@pytest.mark.parametrize("event", EVENTS)
def test_an_old_unwaived_violation_in_head_does_not_block_the_turn(tmp_path: Path, event: str) -> None:
    repo = init_repo(tmp_path)
    _commit(repo, **{"app.py": BAD})
    gate = _regex_gate(tmp_path)
    assert _run(gate, repo, event, BAD + "z = 1\n") == 0
    assert _run(gate, repo, event, BAD + "z = eval(c)\n") == 1


def test_a_whole_file_write_is_diffed_against_the_disk(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "app.py").write_text(BAD, encoding="utf-8")
    gate = _regex_gate(tmp_path)
    assert _run(gate, repo, "pre-tool-use", BAD + "z = 1\n") == 0
    assert _run(gate, repo, "pre-tool-use", BAD + "z = eval(c)\n") == 1


def test_a_new_file_is_all_added_lines(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    _commit(repo, **{"other.py": "q = 1\n"})
    gate = _regex_gate(tmp_path)
    for event in EVENTS:
        assert _run(gate, repo, event, BAD) == 1


# --- dependency_allowlist -------------------------------------------------------------------------

PKG = '{"dependencies": {"requests": "^2"}}\n'
PKG_NEW = '{"dependencies": {"requests": "^2", "evil-pkg": "^1"}}\n'


def _dep_gate(tmp_path: Path) -> Path:
    params = {"manifests": ["package.json"], "allowlist_file": ".chock/allow.txt"}
    return write_gate(
        tmp_path,
        {"kind": "dependency_allowlist", "on": ["tool_use"], "action": "block", "message": "m", "params": params},
    )


def test_a_new_dependency_is_blocked_at_pre_tool(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    _commit(repo, **{"package.json": PKG, ".chock/allow.txt": "requests\n"})
    assert _run(_dep_gate(tmp_path), repo, "pre-tool-use", PKG_NEW, "package.json") == 1
    assert _run(_dep_gate(tmp_path), repo, "pre-tool-use", PKG, "package.json") == 0


def test_a_dependency_added_on_disk_is_blocked_at_stop(tmp_path: Path) -> None:
    """`npm i x` has already written the manifest by the turn's end: the baseline is HEAD."""
    repo = init_repo(tmp_path)
    _commit(repo, **{"package.json": PKG, ".chock/allow.txt": "requests\n"})
    (repo / "package.json").write_text(PKG_NEW, encoding="utf-8")
    assert _run(_dep_gate(tmp_path), repo, "stop", PKG_NEW, "package.json") == 1
    (repo / "package.json").write_text(PKG, encoding="utf-8")
    assert _run(_dep_gate(tmp_path), repo, "stop", PKG, "package.json") == 0


def test_a_new_manifest_at_stop_is_all_new(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    _commit(repo, **{".chock/allow.txt": "requests\n"})
    assert _run(_dep_gate(tmp_path), repo, "stop", PKG_NEW, "package.json") == 1


# --- test_integrity -------------------------------------------------------------------------------

TESTS = "def test_a():\n    assert f(1) == 1\n    assert f(2) == 2\n"
WEAKENED = "def test_a():\n    assert f(1) == 1\n"


def _integrity_gate(tmp_path: Path) -> Path:
    params = {"test_path_regex": r"^tests/", "assertion_pattern": r"^\s*assert\b"}
    return write_gate(
        tmp_path, {"kind": "test_integrity", "on": ["tool_use"], "action": "block", "message": "m", "params": params}
    )


def test_a_deleted_assertion_is_blocked_at_pre_tool(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    _commit(repo, **{"tests/test_a.py": TESTS})
    gate = _integrity_gate(tmp_path)
    added = {"tests/test_a.py": WEAKENED}  # an edit carries its own text, which keeps one assertion
    assert run(gate, "pre-tool-use", None, repo, writes={"tests/test_a.py": WEAKENED}, added=added) == 1
    assert _run(gate, repo, "pre-tool-use", TESTS + "    assert f(3) == 3\n", "tests/test_a.py") == 0


def test_a_deleted_assertion_is_blocked_at_stop(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    _commit(repo, **{"tests/test_a.py": TESTS})
    (repo / "tests/test_a.py").write_text(WEAKENED, encoding="utf-8")
    gate = _integrity_gate(tmp_path)
    assert _run(gate, repo, "stop", WEAKENED, "tests/test_a.py") == 1
    (repo / "tests/test_a.py").write_text(TESTS, encoding="utf-8")
    assert _run(gate, repo, "stop", TESTS, "tests/test_a.py") == 0


def test_an_unrelated_dirty_file_is_not_a_deleted_test(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    _commit(repo, **{"tests/test_a.py": TESTS})
    assert _run(_integrity_gate(tmp_path), repo, "stop", "x = 1\n", "app.py") == 0


# --- wiring ---------------------------------------------------------------------------------------


def test_the_new_kinds_run_at_tool_use() -> None:
    assert {"dependency_allowlist", "test_integrity"} <= WRITE_PATH_KINDS


@pytest.mark.parametrize("kind", ["dependency_allowlist", "test_integrity"])
def test_a_policy_declaring_tool_use_gets_an_in_agent_gate(tmp_path: Path, kind: str) -> None:
    params = (
        {"manifests": ["package.json"], "allowlist_file": "a.txt"}
        if kind == "dependency_allowlist"
        else {"test_path_regex": "^tests/", "assertion_pattern": "assert"}
    )
    gate = {"kind": kind, "on": ["commit", "tool_use"], "action": "block", "message": "m", "params": params}
    policy = tmp_path / ".agents" / "policies" / "p"
    policy.mkdir(parents=True)
    manifest = {
        "id": "p",
        "name": "p",
        "version": "0.1.0",
        "description": "d.",
        "artifact": "hook",
        "enforcement": "block",
        "provenance": {"author": "x", "license": "Apache-2.0", "trust_tier": "sandbox"},
        "hook": {"gate": gate},
    }
    (policy / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    spec = tool_use_gate_spec(policy, tmp_path)
    assert spec is not None
    assert spec["kind"] == kind
    report = Report()
    _validate_gate(gate, "p", report, tool_use_allowed=True)
    assert not report.errors

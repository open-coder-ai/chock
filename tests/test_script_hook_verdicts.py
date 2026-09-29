"""A script-backed git hook may warn (exit 4) or ask (exit 3), not only allow or refuse."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from chock.compile.compiler import compile_policy
from chock.compile.surfaces import Surface
from chock.hooks.installers import get_hooks_dir, install_policy_hooks

POLICY_ID = "word-check"

#: Exits by what a.txt says, printing its own words: the verdict is the script's, not the runner's.
_SCRIPT = """\
import subprocess, sys
text = subprocess.run(["git", "show", ":a.txt"], capture_output=True, text=True, check=False).stdout.strip()
codes = {"warn": 4, "ask": 3, "block": 1, "crash": 7}
if text in codes:
    print("word-check says " + text, file=sys.stderr)
raise SystemExit(codes.get(text, 0))
"""

_MANIFEST = {
    "id": POLICY_ID,
    "name": "Word Check",
    "version": "0.0.1",
    "description": "trigger: committing a.txt. avoid: certain words.",
    "artifact": "rule",
    "enforcement": "block",
    "rule": {"text": "never(commit): certain words\n"},
    "hook": {"script": {"on": ["commit"]}},
    "provenance": {"author": "t"},
    "lifecycle": {"status": "draft"},
}


def _git(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, check=False, capture_output=True, text=True, env={**os.environ, **(env or {})}
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    policy = root / ".agents" / "policies" / POLICY_ID
    (policy / "implementations").mkdir(parents=True)
    (policy / "manifest.yaml").write_text(yaml.safe_dump(_MANIFEST), encoding="utf-8")
    (policy / "implementations" / f"{POLICY_ID}-pre-commit.py").write_text(_SCRIPT, encoding="utf-8")
    compile_policy(policy, targets=[Surface.GIT_HOOK.value], output_root=root / ".chock" / "compiled")
    install_policy_hooks(root, get_hooks_dir(root))
    return root


def _commit(repo: Path, word: str, env: dict | None = None) -> subprocess.CompletedProcess:
    (repo / "a.txt").write_text(word + "\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    return _git(repo, "commit", "-qm", "c", env={"CHOCK_GATE_LOG": "1", **(env or {})})


def _log(repo: Path) -> list[dict]:
    path = repo / ".chock" / "log" / "gate-events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_the_runner_ships_with_a_script_only_policy(repo: Path) -> None:
    """The shim hands an ask or a warn to the runner, so the runner must be there to take it."""
    assert (repo / ".chock" / "bin" / "gate.py").is_file()


def test_exit_zero_commits(repo: Path) -> None:
    assert _commit(repo, "fine").returncode == 0


def test_exit_one_still_refuses(repo: Path) -> None:
    done = _commit(repo, "block")
    assert done.returncode != 0
    assert "word-check says block" in done.stderr


def test_an_unknown_exit_still_refuses(repo: Path) -> None:
    assert _commit(repo, "crash").returncode != 0


def test_exit_four_warns_and_commits(repo: Path) -> None:
    done = _commit(repo, "warn")
    assert done.returncode == 0, done.stderr
    assert "word-check says warn" in done.stderr
    assert [r["verdict"] for r in _log(repo)] == ["warn"]


def test_exit_three_refuses_and_names_the_override(repo: Path) -> None:
    done = _commit(repo, "ask")
    assert done.returncode != 0
    assert "word-check says ask" in done.stderr
    assert f"CHOCK_ALLOW={POLICY_ID}" in done.stderr
    assert [r["verdict"] for r in _log(repo)] == ["ask"]


def test_exit_three_commits_when_a_person_names_the_policy(repo: Path) -> None:
    done = _commit(repo, "ask", {"CHOCK_ALLOW": f"other,{POLICY_ID}"})
    assert done.returncode == 0, done.stderr
    record = _log(repo)[-1]
    assert (record["verdict"], record["override"]) == ("allow", "CHOCK_ALLOW")


def test_a_different_policy_id_does_not_answer(repo: Path) -> None:
    assert _commit(repo, "ask", {"CHOCK_ALLOW": "other"}).returncode != 0


@pytest.mark.parametrize(
    "marker", [{"CLAUDECODE": "1"}, {"AI_AGENT": "claude-code_1_agent"}, {"CHOCK_AGENT_COMMIT": "1"}]
)
def test_an_agent_cannot_answer_for_the_person(repo: Path, marker: dict) -> None:
    done = _commit(repo, "ask", {"CHOCK_ALLOW": POLICY_ID, **marker})
    assert done.returncode != 0
    assert "treated as an agent's" in done.stderr


def test_the_escape_hatch_answers_from_an_agent_terminal(repo: Path) -> None:
    env = {"CHOCK_ALLOW": POLICY_ID, "CLAUDECODE": "1", "CHOCK_AGENT_COMMIT": "0"}
    assert _commit(repo, "ask", env).returncode == 0


def test_a_warn_is_the_same_for_an_agent(repo: Path) -> None:
    assert _commit(repo, "warn", {"CLAUDECODE": "1"}).returncode == 0

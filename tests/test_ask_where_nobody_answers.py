"""What an `ask` does where nobody can answer it: each surface's text names the policy and what happened.

Each test is a row of "What an ask does where nobody can answer" in docs/enforcement-surfaces.md.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import init_repo
from floor_support import FLOOR_TOKEN, base_repo, commit, gate, run_floor, write

from chock.gate.runner import EXIT_ASK, EXIT_WARN, run
from chock.gateway import gates as gateway_gates

POLICY = "demo-policy"
BAD = "BAD = 1\n"


def _gate(repo: Path, action: str = "ask") -> Path:
    path = repo / ".chock" / "compiled" / POLICY / "git-hook" / "gate.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    spec = {
        "kind": "content_regex",
        "on": ["commit", "push", "tool_use"],
        "action": action,
        "message": "no BAD",
        "params": {"content_pattern": "BAD"},
    }
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def _stage(repo: Path, text: str) -> None:
    (repo / "app.py").write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return init_repo(tmp_path)


def test_git_hook_ask_is_refused_and_says_so(repo: Path, capsys: pytest.CaptureFixture) -> None:
    _stage(repo, BAD)
    assert run(_gate(repo), "pre-commit", None, repo) == 1
    assert f"gate: {POLICY} asks a person to decide, and a hook cannot prompt, so this was refused." in (
        capsys.readouterr().err
    )


def test_ci_ask_passes_with_a_note_that_names_the_policy(repo: Path, capsys: pytest.CaptureFixture) -> None:
    _stage(repo, "OK = 1\n")
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True, capture_output=True)
    _stage(repo, BAD)
    subprocess.run(["git", "commit", "-qm", "bad"], cwd=repo, check=True, capture_output=True)
    assert run(_gate(repo), "ci", None, repo, base="HEAD~1") == 0
    out = capsys.readouterr().out
    assert out.startswith(
        f"::warning title=chock {POLICY}::chock {POLICY} asks a person; CI cannot ask, so this passed with this note%0A"
    )


def test_floor_ask_refuses_and_says_so(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = base_repo(tmp_path)
    gate(repo, "floor-token", {**FLOOR_TOKEN, "action": "ask"})
    commit(repo, "gate asks")
    git_base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    write(repo, "src/app.py", "VALUE = 'FLOOR-TOKEN-9'\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys, "--base", git_base.stdout.strip())
    assert code == 1
    assert "FAIL floor-token [base] (ask): chock floor-token asks a person; CI cannot ask, so the floor refused" in out


def test_gateway_ask_blocks_and_says_so() -> None:
    spec = {
        "policy_id": "gw",
        "kind": "content_regex",
        "action": "ask",
        "message": "no BAD",
        "params": {"content_pattern": "BAD"},
    }
    assert gateway_gates.evaluate([spec], "t", {"x": "BAD"}) == (
        "[gw] no BAD (asks a person; the gateway cannot prompt, so it blocks)"
    )


def test_stop_ask_is_a_warning_that_says_so(repo: Path, capsys: pytest.CaptureFixture) -> None:
    assert run(_gate(repo), "stop", None, repo, writes={"app.py": BAD}) == EXIT_WARN
    assert f"chock {POLICY} asks a person; the turn has ended and nobody can answer, so this is a warning" in (
        capsys.readouterr().err
    )


def test_tool_use_ask_prompts_in_every_mode(repo: Path, capsys: pytest.CaptureFixture) -> None:
    """The host prompts at a write; the words it shows name the policy in tests/test_ask_reason_wire.py."""
    assert run(_gate(repo), "pre-tool-use", None, repo, writes={"app.py": BAD}) == EXIT_ASK
    assert "no BAD" in capsys.readouterr().err

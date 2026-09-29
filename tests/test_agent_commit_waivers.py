"""A waiver is a human's decision: a commit marked as an agent's does not honour one it adds."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import init_repo, write_gate

from chock.gate.runner import AGENT_COMMIT_ENV, WAIVABLE_EVENTS, run

WAIVER = r"chock:\s*allow\s+sql"
UNSAFE = 'q = "select " + name\n'
WAIVED = 'q = "select " + name  # chock: allow sql\n'


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repo(tmp_path: Path, head_text: str = "x = 1\n") -> Path:
    repo = init_repo(tmp_path)
    (repo / "app.py").write_text(head_text, encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "base")
    return repo


def _gate(tmp_path: Path, scan: str = "added_lines", kind: str = "content_regex") -> Path:
    params = {"scan": scan, "content_pattern": r'"select "\s*\+', "allowlist_pragma": WAIVER}
    return write_gate(tmp_path, {"kind": kind, "on": ["commit"], "action": "block", "message": "sql", "params": params})


def _stage(repo: Path, text: str) -> None:
    (repo / "app.py").write_text(text, encoding="utf-8")
    _git(repo, "add", "app.py")


@pytest.fixture(autouse=True)
def _human_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(AGENT_COMMIT_ENV, raising=False)


def test_human_commit_honours_a_waiver_it_adds(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, WAIVED)
    assert run(_gate(tmp_path), "pre-commit", None, repo) == 0


def test_agent_commit_refuses_a_waiver_it_adds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    repo = _repo(tmp_path)
    _stage(repo, WAIVED)
    monkeypatch.setenv(AGENT_COMMIT_ENV, "1")
    assert run(_gate(tmp_path), "pre-commit", None, repo) == 1
    assert "not honoured" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["1", "true", "yes"])
def test_the_opt_in_var_forces_agent_treatment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    repo = _repo(tmp_path)
    _stage(repo, WAIVED)
    monkeypatch.setenv(AGENT_COMMIT_ENV, value)
    assert run(_gate(tmp_path), "pre-commit", None, repo) == 1


@pytest.mark.parametrize(
    "env", [{AGENT_COMMIT_ENV: "0"}, {AGENT_COMMIT_ENV: ""}, {"TERM_PROGRAM": "vscode"}, {"CLAUDECODE": "0"}]
)
def test_unrelated_or_off_env_is_a_human_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: dict) -> None:
    repo = _repo(tmp_path)
    _stage(repo, WAIVED)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert run(_gate(tmp_path), "pre-commit", None, repo) == 0


def test_agent_commit_still_honours_a_waiver_already_in_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, head_text=WAIVED)
    _stage(repo, WAIVED + "y = 2\n")
    monkeypatch.setenv(AGENT_COMMIT_ENV, "1")
    assert run(_gate(tmp_path, scan="staged_blob"), "pre-commit", None, repo) == 0


def test_agent_commit_does_not_honour_a_waiver_on_a_line_new_to_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, head_text=WAIVED)
    _stage(repo, WAIVED + WAIVED.replace("name", "other"))
    monkeypatch.setenv(AGENT_COMMIT_ENV, "1")
    assert run(_gate(tmp_path, scan="staged_blob"), "pre-commit", None, repo) == 1


def test_agent_commit_leaves_a_clean_change_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _stage(repo, "x = 2\n")
    monkeypatch.setenv(AGENT_COMMIT_ENV, "1")
    assert run(_gate(tmp_path), "pre-commit", None, repo) == 0


def test_agent_commit_is_not_a_waivable_event() -> None:
    from chock.gate.runner import AGENT_COMMIT_EVENT

    assert AGENT_COMMIT_EVENT not in WAIVABLE_EVENTS


def test_script_gate_is_told_the_agent_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A policy script reads `event`; an agent commit must not arrive as commit, push or ci."""
    repo = _repo(tmp_path)
    _stage(repo, UNSAFE)
    script = tmp_path / "gate_script.py"
    script.write_text(
        "import json, sys\nsys.exit(0 if json.load(sys.stdin)['event'] in {'commit', 'push', 'ci'} else 1)\n",
        encoding="utf-8",
    )
    gate = write_gate(
        tmp_path,
        {"kind": "script", "on": ["commit"], "action": "block", "message": "s", "params": {"script": str(script)}},
    )
    assert run(gate, "pre-commit", None, repo) == 0
    monkeypatch.setenv(AGENT_COMMIT_ENV, "1")
    assert run(gate, "pre-commit", None, repo) == 1

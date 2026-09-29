"""A commit is an agent's when its environment says so: no opt-in needed for a vendor that is witnessed."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import init_repo

from chock import evidence
from chock.gate.runner import AGENT_COMMIT_ENV, CONFIG_AGENT_ENV_KEY, agent_commit, agent_signal, run


def _config(repo: Path, text: str) -> None:
    (repo / ".chock").mkdir(exist_ok=True)
    (repo / ".chock" / "config.yaml").write_text(text, encoding="utf-8")


def test_a_bare_environment_is_a_person(tmp_path: Path) -> None:
    assert agent_signal(tmp_path) is None
    assert not agent_commit()


@pytest.mark.parametrize(
    ("env", "signal"),
    [
        ({"CLAUDECODE": "1"}, "CLAUDECODE=1"),
        ({"AI_AGENT": "claude-code_2-1-285_agent"}, "AI_AGENT"),
        ({AGENT_COMMIT_ENV: "1"}, AGENT_COMMIT_ENV),
        ({AGENT_COMMIT_ENV: "yes"}, AGENT_COMMIT_ENV),
    ],
)
def test_a_marker_makes_the_commit_an_agents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: dict, signal: str
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert agent_signal(tmp_path) == signal
    assert agent_commit(tmp_path)


@pytest.mark.parametrize("env", [{"CLAUDECODE": "0"}, {"CLAUDECODE": "true"}, {"CLAUDECODE": ""}, {"AI_AGENT": "  "}])
def test_only_the_witnessed_values_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: dict) -> None:
    """`CLAUDECODE` is the string `1` and `AI_AGENT` must say something: a stray value is not a marker."""
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert agent_signal(tmp_path) is None


@pytest.mark.parametrize("off", ["0", "false", "no", "off", "FALSE", " 0 "])
def test_an_explicit_off_wins_over_every_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, off: str) -> None:
    _config(tmp_path, f"{CONFIG_AGENT_ENV_KEY}: [CODEX_SANDBOX]\n")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("AI_AGENT", "claude-code_1_agent")
    monkeypatch.setenv("CODEX_SANDBOX", "seatbelt")
    monkeypatch.setenv(AGENT_COMMIT_ENV, off)
    assert agent_signal(tmp_path) is None


def test_an_empty_opt_in_falls_through_to_detection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(AGENT_COMMIT_ENV, "")
    monkeypatch.setenv("CLAUDECODE", "1")
    assert agent_commit(tmp_path)


@pytest.mark.parametrize(
    "text",
    [
        f"{CONFIG_AGENT_ENV_KEY}: [CODEX_SANDBOX, CURSOR_TRACE_ID]\n",
        f"{CONFIG_AGENT_ENV_KEY}: ['CODEX_SANDBOX']  # captured 2026\n",
        f"{CONFIG_AGENT_ENV_KEY}:\n  - CURSOR_TRACE_ID\n  # a note\n\n  - CODEX_SANDBOX\nchock:\n  supported_agents: [claude]\n",
        f'chock:\n  supported_agents: [claude]\n{CONFIG_AGENT_ENV_KEY}:\n  - "CODEX_SANDBOX"\n',
        f"{CONFIG_AGENT_ENV_KEY}: CODEX_SANDBOX\n",
    ],
)
def test_a_configured_variable_marks_an_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    _config(tmp_path, text)
    assert agent_signal(tmp_path) is None
    monkeypatch.setenv("CODEX_SANDBOX", "seatbelt")
    assert agent_signal(tmp_path) == "CODEX_SANDBOX"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "chock:\n  supported_agents: [claude]\n",
        f"{CONFIG_AGENT_ENV_KEY}: []\n",
        f"{CONFIG_AGENT_ENV_KEY}:\nchock:\n  - CODEX_SANDBOX\n",
        f"  {CONFIG_AGENT_ENV_KEY}: [CODEX_SANDBOX]\n",
        f"{CONFIG_AGENT_ENV_KEY}: [not a name, 9BAD]\n",
    ],
)
def test_a_config_that_names_nothing_marks_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    _config(tmp_path, text)
    monkeypatch.setenv("CODEX_SANDBOX", "seatbelt")
    assert agent_signal(tmp_path) is None


def test_a_configured_variable_must_be_non_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _config(tmp_path, f"{CONFIG_AGENT_ENV_KEY}: [CODEX_SANDBOX]\n")
    monkeypatch.setenv("CODEX_SANDBOX", "")
    assert agent_signal(tmp_path) is None


def test_a_missing_or_unreadable_config_is_no_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEX_SANDBOX", "seatbelt")
    assert agent_signal(tmp_path) is None
    (tmp_path / ".chock").mkdir()
    (tmp_path / ".chock" / "config.yaml").write_bytes(b"\xff\xfe\x00")
    assert agent_signal(tmp_path) is None


def test_the_repo_config_loader_and_the_runner_read_the_same_names(tmp_path: Path) -> None:
    """The runner reads one key without YAML; the real loader must agree on what that key holds."""
    from chock.config import load_config

    _config(tmp_path, f"chock:\n  supported_agents: [claude]\n{CONFIG_AGENT_ENV_KEY}:\n  - A_B\n  - C_D  # x\n")
    assert load_config(tmp_path)[CONFIG_AGENT_ENV_KEY] == ["A_B", "C_D"]


# --- the gate acts on it --------------------------------------------------------------------------

WAIVER = r"chock:\s*allow\s+sql"
WAIVED = 'q = "select " + name  # chock: allow sql\n'


def _waivable_gate(repo: Path) -> Path:
    params = {"content_pattern": r'"select "\s*\+', "allowlist_pragma": WAIVER}
    spec = {"kind": "content_regex", "on": ["commit"], "action": "block", "message": "sql", "params": params}
    gate = repo / "gate.json"
    gate.write_text(json.dumps(spec), encoding="utf-8")
    return gate


def _stage_waived(repo: Path) -> None:
    (repo / "app.py").write_text(WAIVED, encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True, capture_output=True)


@pytest.mark.parametrize("env", [{"CLAUDECODE": "1"}, {"AI_AGENT": "claude-code_1_agent"}])
def test_a_detected_agent_commit_does_not_honour_the_waiver_it_adds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, env: dict
) -> None:
    repo = init_repo(tmp_path)
    _stage_waived(repo)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert run(_waivable_gate(repo), "pre-commit", None, repo) == 1
    err = capsys.readouterr().err
    assert "not honoured" in err
    assert f"{AGENT_COMMIT_ENV}=0" in err


def test_a_configured_marker_is_read_from_the_repo_the_gate_runs_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(tmp_path)
    _config(repo, f"{CONFIG_AGENT_ENV_KEY}: [CODEX_SANDBOX]\n")
    _stage_waived(repo)
    gate = _waivable_gate(repo)
    assert run(gate, "pre-commit", None, repo) == 0
    monkeypatch.setenv("CODEX_SANDBOX", "seatbelt")
    assert run(gate, "pre-commit", None, repo) == 1


def test_the_escape_hatch_lets_a_person_commit_in_an_agents_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(tmp_path)
    _stage_waived(repo)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv(AGENT_COMMIT_ENV, "0")
    assert run(_waivable_gate(repo), "pre-commit", None, repo) == 0


# --- the evidence ---------------------------------------------------------------------------------


def test_claude_code_is_the_one_witnessed_marker() -> None:
    """Other vendors' markers stay unverified until a probe records them; the ledger says which is which."""
    rows = [w for w in evidence.witnesses() if w.surface == evidence.GIT_HOOK_ENV]
    assert [w.agent for w in rows] == ["claude_code"]
    assert "CLAUDECODE=1" in rows[0].client
    assert "AI_AGENT" in rows[0].client

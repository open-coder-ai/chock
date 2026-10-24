"""An agent cannot switch chock off: the commands that change what it enforces refuse under an agent marker."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import init_repo
from decision_log_support import records

from chock import cli
from chock.config import policy_status
from chock.gate.runner.actor import agent_signal
from chock.stop_common import PERSON_ONLY_POLICY

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
POLICY = "block-no-verify"
#: Every command that writes `.chock/config.yaml`, `chock.lock` or the compiled tree.
PERSON_ONLY = ("sync", "recompile", "install-hooks", "enable", "disable", "add", "remove", "init", "compile")
REFUSED = "chock: refused: this shell is marked as an agent's"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A scaffolded repository with one policy compiled, as a person left it."""
    (tmp_path / "repo").mkdir()
    root = init_repo(tmp_path / "repo")
    assert cli.main(["init", str(root), "--skip-hooks"]) == 0
    shutil.copytree(FRAMEWORK_ROOT / ".agents" / "policies" / POLICY, root / ".agents" / "policies" / POLICY)
    assert cli.main(["recompile", "--repo", str(root), "--skip-hooks"]) == 0
    assert (root / ".chock" / "compiled" / POLICY).is_dir()
    return root


def _disable_by_hand(root: Path) -> None:
    """The review's wrapper script: the config edit itself, which a catalog guard refuses and chock here does not."""
    config = root / ".chock" / "config.yaml"
    config.write_text(config.read_text(encoding="utf-8") + f"policies:\n  disabled: [{POLICY}]\n", encoding="utf-8")


def test_the_disarm_chain_is_refused_at_sync(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _disable_by_hand(repo)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.delenv("CHOCK_GATE_LOG", raising=False)
    monkeypatch.setenv("CHOCK_LOG_LEVEL", "info")
    assert cli.main(["sync", "--repo", str(repo)]) == 1
    err = capsys.readouterr().err
    assert REFUSED in err and "(CLAUDECODE=1)" in err
    assert "a person runs `chock sync` from their own shell" in err
    assert (repo / ".chock" / "compiled" / POLICY).is_dir(), "the compiled gate must still be there"
    [record] = records(repo / ".chock" / "log" / "gate-events.jsonl")
    assert record["policy_id"] == PERSON_ONLY_POLICY and record["event"] == "sync"
    assert record["verdict"] == "block" and record["actor"] == "agent:claude_code"


@pytest.mark.parametrize("command", PERSON_ONLY)
@pytest.mark.parametrize(
    "env",
    [
        {"CLAUDECODE": "1"},
        {"AI_AGENT": "claude-code_1_agent"},
        {"CHOCK_AGENT_COMMIT": "1"},
        {"CLAUDECODE": "1", "CHOCK_AGENT_COMMIT": "0"},
    ],
    ids=["claudecode", "ai_agent", "opt_in", "hatch_under_marker"],
)
def test_every_person_only_command_refuses_an_agent(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str, env: dict
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert cli.main([command, "--repo", str(repo)]) == 1
    assert f"a person runs `chock {command}` from their own shell" in capsys.readouterr().err


def test_a_configured_marker_is_read_from_the_named_repo(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = repo / ".chock" / "config.yaml"
    config.write_text(config.read_text(encoding="utf-8") + "agent_commit_env: [CODEX_SANDBOX]\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_SANDBOX", "seatbelt")
    assert cli.main(["sync", f"--repo={repo}", "--skip-hooks"]) == 1
    assert "(CODEX_SANDBOX)" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [["sync", "--check"], ["recompile", "--check"], ["status"], ["check", "--only", "validate"]],
    ids=["sync-check", "recompile-check", "status", "check"],
)
def test_reading_commands_stay_open_to_an_agent(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    monkeypatch.setenv("CLAUDECODE", "1")
    cli.main([*argv, "--repo", str(repo)])
    assert REFUSED not in capsys.readouterr().err


def test_a_persons_shell_still_runs_them(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No vendor marker, with or without `CHOCK_AGENT_COMMIT=0`: the person's own shell."""
    monkeypatch.setenv("CHOCK_AGENT_COMMIT", "0")
    assert cli.main(["disable", POLICY, "--repo", str(repo)]) == 0
    assert not (repo / ".chock" / "compiled" / POLICY).exists()
    assert cli.main(["enable", POLICY, "--repo", str(repo)]) == 0
    assert (repo / ".chock" / "compiled" / POLICY).is_dir()


def test_help_still_lists_every_command() -> None:
    assert all(len(entry) == 3 for entry in cli.COMMANDS.values())  # handler, help, person-only
    assert {name for name, (_, _, person_only) in cli.COMMANDS.items() if person_only} == set(PERSON_ONLY)


# --- an uncommitted disable changes nothing for an agent ---------------------------------------------------


def test_a_disable_counts_for_an_agent_only_once_committed() -> None:
    working = {"policies": {"disabled": [POLICY]}}
    assert policy_status(working, POLICY)["state"] == "disabled"
    assert policy_status(working, POLICY, committed={})["state"] == "enabled"
    assert policy_status(working, POLICY, committed=working)["state"] == "disabled"
    assert policy_status({}, POLICY, committed=working)["state"] == "enabled"
    assert policy_status(working, POLICY, {"mandatory": True}, committed=working)["state"] == "enabled"


def test_the_committed_config_is_what_head_holds(repo: Path) -> None:
    from chock.config import committed_config_text

    assert committed_config_text(repo) is None
    _disable_by_hand(repo)
    assert committed_config_text(repo) is None
    from subprocess import run

    run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    run(["git", "-C", str(repo), "commit", "-qm", "off"], check=True, capture_output=True)
    assert json.dumps(committed_config_text(repo)).count(POLICY) == 1


# --- `sync --committed`: the one form an agent may run, on an untouched committed tree ----------------------


def _commit_all(root: Path) -> None:
    """Commit the scaffold as the person left it, so HEAD holds the config, lock and policies."""
    git = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "add", "-A", "-f"], check=True, capture_output=True)
    subprocess.run([*git, "commit", "-qm", "scaffold", "--no-verify"], check=True, capture_output=True)


@pytest.fixture
def committed(repo: Path) -> Path:
    _commit_all(repo)
    return repo


def test_an_agent_runs_sync_committed_on_a_clean_tree(committed: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["sync", "--committed", "--repo", str(committed)]) == 0
    assert (committed / ".chock" / "compiled" / POLICY).is_dir()


@pytest.mark.parametrize("target", [".chock/config.yaml", "chock.lock", f".agents/policies/{POLICY}/manifest.yaml"])
def test_an_agent_is_refused_sync_committed_naming_a_modified_input(
    committed: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], target: str
) -> None:
    path = committed / target
    path.write_text(path.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["sync", "--committed", "--repo", str(committed)]) == 1
    err = capsys.readouterr().err
    assert "a person runs `chock sync` from their own shell" in err and target in err


def test_an_agent_is_refused_sync_committed_for_an_untracked_policy_file(
    committed: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (committed / ".agents" / "policies" / POLICY / "extra.txt").write_text("x", encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["sync", "--committed", "--repo", str(committed)]) == 1
    assert "extra.txt" in capsys.readouterr().err


def test_an_agent_is_refused_sync_committed_when_head_cannot_be_read(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["sync", "--committed", "--repo", str(repo)]) == 1
    assert "a person runs `chock sync` from their own shell" in capsys.readouterr().err


@pytest.mark.parametrize("extra", [["--ci"], ["--skip-hooks"], ["--skills"], ["--agents", "claude_code"]])
def test_sync_committed_with_any_other_flag_is_refused(
    committed: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], extra: list[str]
) -> None:
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["sync", "--committed", *extra, "--repo", str(committed)]) == 1
    assert "a person runs `chock sync` from their own shell" in capsys.readouterr().err


def test_sync_committed_with_another_flag_is_refused_for_a_person_too(
    committed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("CLAUDECODE", "AI_AGENT", "CHOCK_AGENT_COMMIT"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit) as exc:
        cli.main(["sync", "--committed", "--ci", "--repo", str(committed)])
    assert exc.value.code == 2


def test_without_a_marker_sync_committed_is_a_plain_sync(committed: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CLAUDECODE", "AI_AGENT", "CHOCK_AGENT_COMMIT"):
        monkeypatch.delenv(name, raising=False)
    config = committed / ".chock" / "config.yaml"
    config.write_text(config.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    assert cli.main(["sync", "--committed", "--repo", str(committed)]) == 0


def test_the_agent_ok_flag_is_declared_in_commands_json_for_sync_alone() -> None:
    assert cli.AGENT_OK_FLAG == {"sync": "--committed"}


BUNDLE_WRITES = (["bundle", "off", "scan-secrets"], ["bundle", "on", "scan-secrets"], ["bundle", "status", "--adopt"])


@pytest.mark.parametrize("argv", BUNDLE_WRITES, ids=["off", "on", "adopt"])
def test_bundle_writes_refuse_an_agent(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> None:
    monkeypatch.chdir(repo)
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(argv) == 1
    assert REFUSED in capsys.readouterr().err
    assert not (repo / ".chock" / "guardrails.json").exists()
    assert not (repo / ".chock" / "state" / "guardrails.sha256").exists()


def test_bundle_status_stays_open_to_an_agent(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    monkeypatch.setenv("CLAUDECODE", "1")
    cli.main(["bundle", "status"])
    assert REFUSED not in capsys.readouterr().err


def test_a_marker_named_only_in_the_committed_config_still_identifies_an_agent(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = repo / ".chock" / "config.yaml"
    config.write_text(config.read_text(encoding="utf-8") + "agent_commit_env: [CODEX_SANDBOX]\n", encoding="utf-8")
    _commit_all(repo)
    config.write_text(
        config.read_text(encoding="utf-8").replace("agent_commit_env: [CODEX_SANDBOX]\n", ""), encoding="utf-8"
    )
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("AI_AGENT", raising=False)
    monkeypatch.setenv("CODEX_SANDBOX", "seatbelt")
    assert agent_signal(repo) == "CODEX_SANDBOX"


def test_bundle_off_from_a_subdirectory_reads_the_repo_roots_config(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = repo / ".chock" / "config.yaml"
    config.write_text(config.read_text(encoding="utf-8") + "agent_commit_env: [CODEX_SANDBOX]\n", encoding="utf-8")
    nested = repo / "src" / "pkg"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("AI_AGENT", raising=False)
    monkeypatch.setenv("CODEX_SANDBOX", "seatbelt")
    assert cli.main(["bundle", "off", "scan-secrets"]) == 1
    assert "(CODEX_SANDBOX)" in capsys.readouterr().err

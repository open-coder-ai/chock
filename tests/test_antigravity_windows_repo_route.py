"""`chock sync` follows the plugin's rule (chock#300): built on Windows for a store whose data says `quote_free`, the
repo route's hook commands carry no quote or space either (org-plan witness/results/witness-antigravity-2026-10-18.md).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from bundle_fixtures import hook_commands
from conftest import baseline_policy, init_repo
from runtime_payloads import DENY_ON_THE_WIRE, PAYLOADS

from chock import vendors
from chock.hooks import in_agent_generic, launch
from chock.hooks.in_agent_install import installed_policy_ids
from chock.plugin import hook_dir
from chock.plugin.clients import CLIENTS
from chock.scaffold.recompile import recompile

pytestmark = pytest.mark.skipif(shutil.which("git") is None or shutil.which("sh") is None, reason="git and sh required")

AGENT = "antigravity"
POLICIES = ("block-destructive-commands", "block-invisible-unicode")


@pytest.fixture
def on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hook_dir, "build_windows", lambda: True)


def _synced(tmp_path: Path, agent: str = AGENT) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    repo = init_repo(tmp_path)
    for policy in POLICIES:
        shutil.copytree(baseline_policy(policy), repo / ".agents" / "policies" / policy)
    recompile(repo, [agent], skip_hooks=False)
    return repo


def _commands(repo: Path, vendor: str = AGENT) -> list[str]:
    return hook_commands(json.loads((repo / vendors.config_path(vendor)).read_text(encoding="utf-8")))


def _tree(repo: Path) -> dict[str, bytes]:
    return {
        p.relative_to(repo).as_posix(): p.read_bytes() for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts
    }


def _run(command: str, cwd: Path, payload: dict) -> subprocess.CompletedProcess:
    """git.exe's argv once cmd.exe strips each caret: with no quote in the line, words split at spaces."""
    argv = re.sub(r"\^(.)", r"\1", command).split(" ")
    return subprocess.run(
        argv, cwd=cwd, input=json.dumps(payload), capture_output=True, text=True, check=False, timeout=60
    )


def _payload(repo: Path, shell: str) -> dict:
    return json.loads(json.dumps(PAYLOADS[AGENT](shell)).replace('"/x"', json.dumps(repo.as_posix())))


def test_the_windows_repo_command_has_no_quote_or_space_in_any_argument(tmp_path: Path, on_windows: None) -> None:
    commands = _commands(_synced(tmp_path))
    assert any(" --guard " in c for c in commands) and any("--stop-check" in c for c in commands)
    for command in commands:
        assert not re.search(r"""["'%\t]""", command), command
        assert all(word for word in command.split(" ")), command
        assert not re.search(r"[|&<>()^]", re.sub(r"\^[|&<>()]", "", command)), command
        assert command.startswith(f"git -c alias.{launch.ALIAS}=!test${{IFS}}-f${{IFS}}{launch.LAUNCHER_REL}^|^|")


def test_git_sh_runs_the_alias_after_cmd_strips_the_carets_and_the_guard_denies(
    tmp_path: Path, on_windows: None
) -> None:
    repo = _synced(tmp_path)
    guards = [c for c in _commands(repo) if " --guard " in c]
    denied = [_run(c, repo, _payload(repo, "rm -rf /")) for c in guards]
    assert any(p.returncode == 0 and f'"{DENY_ON_THE_WIRE[AGENT]}"' in p.stdout for p in denied), denied
    assert not any(DENY_ON_THE_WIRE[AGENT] in _run(c, repo, _payload(repo, "ls")).stdout for c in guards)


def test_a_missing_launcher_refuses_with_exit_2_inside_git_sh(tmp_path: Path, on_windows: None) -> None:
    repo = _synced(tmp_path)
    (repo / launch.LAUNCHER_REL).unlink()
    done = _run(_commands(repo)[0], repo, _payload(repo, "ls"))
    assert done.returncode == 2, done
    assert f"chock: no {launch.LAUNCHER_REL} here, run chock sync --repo ." in done.stderr


def test_sync_reads_its_own_quote_free_entries_back_and_a_second_sync_changes_nothing(
    tmp_path: Path, on_windows: None
) -> None:
    repo = _synced(tmp_path)
    config = repo / vendors.config_path(AGENT)
    before = config.read_bytes()
    assert set(POLICIES) <= installed_policy_ids(repo, AGENT)
    recompile(repo, [AGENT], skip_hooks=False)
    assert config.read_bytes() == before


def test_off_windows_the_repo_command_is_the_quoted_form(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hook_dir, "build_windows", lambda: False)
    assert all(c.startswith('git -c "alias.') for c in _commands(_synced(tmp_path)))


@pytest.mark.parametrize(
    "agent", sorted({c.agent for c in CLIENTS.values()} & set(vendors.in_agent_vendors()) - {AGENT})
)
def test_every_other_client_syncs_the_same_bytes_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent: str
) -> None:
    name = next(n for n, v in vendors.CHOCK_AGENT.items() if v == agent)
    off = _tree(_synced(tmp_path / "off", name))
    monkeypatch.setattr(hook_dir, "build_windows", lambda: True)
    assert _tree(_synced(tmp_path / "on", name)) == off


def test_only_the_quote_free_store_s_agent_is_synced_quote_free(on_windows: None) -> None:
    assert [a for a in sorted(vendors.in_agent_vendors()) if in_agent_generic.quote_free(a)] == [AGENT]


@pytest.mark.parametrize("arg", ["a b/c.py", "a&b/c.py", "50%/c.py", "a(x)/c.py"])
def test_an_argument_the_quote_free_command_cannot_carry_is_refused(arg: str) -> None:
    with pytest.raises(ValueError, match="through cmd.exe on Windows"):
        launch.hook_command_quote_free(launch.hook_command(".chock/bin/x.py", "--guard", arg))

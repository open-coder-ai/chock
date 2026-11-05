"""Antigravity on Windows runs a hook `command` through cmd.exe and passes `"` on as `\\"`: chock emits it quote-free.

Witnessed by the owner 2026-10-18 (org-plan witness/results/witness-antigravity-2026-10-18.md): a single- or
double-quoted alias split inside git.exe; `git -c alias.chock-sh=!sh chock-sh <launcher> <args>` ran.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from bundle_fixtures import GUARD_ID, bundle, hook_commands, make_members, project, write
from multi_support import seen_through
from runtime_payloads import DENY_ON_THE_WIRE, PAYLOADS

from chock.hooks import launch
from chock.plugin import hook_dir, store
from chock.plugin.bundle_build import CLIENTS, merged_files

pytestmark = pytest.mark.skipif(shutil.which("git") is None or shutil.which("sh") is None, reason="git and sh required")

AGENT = "antigravity"
QUOTED_TOOLS = re.compile(r"""["']""")


@pytest.fixture
def on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hook_dir, "build_windows", lambda: True)


def _package(tmp_path: Path, folder: Path) -> tuple[Path, list[str]]:
    members = make_members(tmp_path)
    files = merged_files(AGENT, bundle(members), members, tmp_path)
    out = write(folder, hook_dir.resolve_root(files, folder, AGENT))
    return out, hook_commands(json.loads((out / "hooks.json").read_text(encoding="utf-8")))


def _cmd_argv(command: str) -> list[str]:
    """What git.exe's argv is after cmd.exe strips each caret: with no quote in the line, words split at spaces."""
    return re.sub(r"\^(.)", r"\1", command).split(" ")


def _run(command: str, cwd: Path, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        _cmd_argv(command), cwd=cwd, input=json.dumps(payload), capture_output=True, text=True, check=False, timeout=60
    )


def test_the_windows_command_has_no_quote_or_space_in_any_argument_and_escapes_every_cmd_operator(
    tmp_path: Path, on_windows: None
) -> None:
    out, commands = _package(tmp_path, tmp_path / "pkg")
    assert any(" --guard " in seen_through(c, out) for c in commands) and any("--stop-check" in c for c in commands)
    assert any(" --bundle " in c for c in commands) and any(" --verify " in c for c in commands)
    for command in commands:
        assert not QUOTED_TOOLS.search(command), command
        assert "%" not in command and "\t" not in command
        assert all(word for word in command.split(" ")), command
        bare = re.sub(r"\^[|&<>()]", "", command)
        assert not re.search(r"[|&<>()^]", bare), command
        assert command.startswith(f"git -c alias.{launch.PLUGIN_ALIAS}=!")


def test_git_sh_runs_the_alias_after_cmd_strips_the_carets_and_the_guard_denies(
    tmp_path: Path, on_windows: None
) -> None:
    out, commands = _package(tmp_path, tmp_path / "pkg")
    repo = project(tmp_path)

    def answers(shell: str) -> list[subprocess.CompletedProcess]:
        payload = json.loads(json.dumps(PAYLOADS[AGENT](shell)).replace('"/x"', json.dumps(repo.as_posix())))
        return [_run(c, repo, payload) for c in commands if " --guard " in seen_through(c, out)]

    denied = answers("rm -rf /")
    assert any(p.returncode == 0 and f'"{DENY_ON_THE_WIRE[AGENT]}"' in p.stdout for p in denied), denied
    assert not any(DENY_ON_THE_WIRE[AGENT] in p.stdout for p in answers("ls"))
    assert (out / "scripts" / launch.PLUGIN_LAUNCHER).is_file()


def test_a_missing_launcher_refuses_with_exit_2_inside_git_sh(tmp_path: Path, on_windows: None) -> None:
    out, commands = _package(tmp_path, tmp_path / "pkg")
    (out / "scripts" / launch.PLUGIN_LAUNCHER).unlink()
    done = _run(commands[0], project(tmp_path), PAYLOADS[AGENT]("ls"))
    assert done.returncode == 2, done
    assert "chock: the plugin launcher is missing, so this call cannot be checked. Refusing." in done.stderr


@pytest.mark.parametrize("name", ["Jo Smith", "a&b", "a^b", "50%", "a(x86)", "a'b", "a!b", "a*b"])
def test_a_folder_the_quote_free_command_cannot_carry_is_refused_at_install(
    tmp_path: Path, on_windows: None, name: str
) -> None:
    members = make_members(tmp_path)
    files = merged_files(AGENT, bundle(members), members, tmp_path)
    folder = tmp_path / name / "pkg"
    with pytest.raises(ValueError, match="through cmd.exe on Windows") as caught:
        hook_dir.resolve_root(files, folder, AGENT)
    assert folder.as_posix() in str(caught.value) and "choose another --dest" in str(caught.value)


def test_a_spaced_folder_is_still_carried_quoted_off_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hook_dir, "build_windows", lambda: False)
    members = make_members(tmp_path)
    files = merged_files(AGENT, bundle(members), members, tmp_path)
    resolved = hook_dir.resolve_root(files, tmp_path / "Jo Smith" / "pkg", AGENT)
    launcher = f'"{(tmp_path / "Jo Smith" / "pkg").as_posix()}/scripts/launch.sh"'
    assert all(launcher in c for c in hook_commands(json.loads(resolved[Path("hooks.json")])))


@pytest.mark.parametrize("fmt", sorted(set(CLIENTS) - {AGENT}))
def test_every_other_client_builds_the_same_bytes_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fmt: str
) -> None:
    members = make_members(tmp_path)
    guard = next(m for m in members if m.id == GUARD_ID)
    before = CLIENTS[fmt].files(guard.policy_dir, guard.manifest, tmp_path)
    merged_before = merged_files(fmt, bundle(members), members, tmp_path)
    monkeypatch.setattr(hook_dir, "build_windows", lambda: True)
    assert CLIENTS[fmt].files(guard.policy_dir, guard.manifest, tmp_path) == before
    assert merged_files(fmt, bundle(members), members, tmp_path) == merged_before


def test_only_antigravity_records_a_quote_free_windows_runner() -> None:
    assert [fmt for fmt in sorted(CLIENTS) if store.windows_hook_command(fmt)] == [AGENT]
    assert store.windows_hook_command(AGENT) == hook_dir.QUOTE_FREE

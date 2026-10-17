"""GAP-1b: every `chock install` bundle carries one matcher-less stop check, so a stop refuses a Read on the plugin route."""

from __future__ import annotations

import io
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from bundle_fixtures import ADVISORY_ID, ALL_ROOTS, GUARD_ID, bundle, hook_commands, make_members, project, write
from conftest import run_hook_command
from decision_log_support import hook_env

from chock import stop as chock_stop
from chock import vendors
from chock.gate.runner import halt
from chock.guardrails import plugin as guardrails
from chock.hooks import stop_check
from chock.hooks.stop_check import STOP_CHECK_FLAG
from chock.plugin.bundle_build import CLIENTS, Member, merged_files
from chock.plugin.store import SCRIPTS_TEMPLATE

#: The clients whose pre-tool payload is Claude-shaped, so one Read payload drives each.
E2E = ("claude", "devin")
DENY = {"claude": "deny", "devin": "block"}
#: Project-root signals a client may set; the hook here runs with none, as a session no client places.
PROJECT_DIRS = ("CLAUDE_PROJECT_DIR", "GEMINI_PROJECT_DIR", "OPENHANDS_PROJECT_DIR")


def _hooks(client: str, root: Path) -> Any:
    members = make_members(root)
    files = merged_files(client, bundle(members), members, root)
    return json.loads(files[Path(CLIENTS[client].layout()[1])])


def _pre_tool_groups(client: str, doc: Any) -> list[dict]:
    """Every entry under the client's pre-tool event, whatever its dialect (a flat rule list for kimi)."""
    event = vendors.pre_tool_event(CLIENTS[client].agent)
    if isinstance(doc, list):
        return [rule for rule in doc if rule.get("event") == event]
    events = doc.get("hooks", doc.get("agentseam", doc))
    return list(events.get(event, []))


@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_every_bundle_carries_one_matcherless_stop_check(tmp_path: Path, client: str) -> None:
    doc = _hooks(client, tmp_path)
    stops = [c for c in hook_commands(doc) if STOP_CHECK_FLAG in c]
    assert len(stops) == 1, stops
    [group] = [g for g in _pre_tool_groups(client, doc) if any(STOP_CHECK_FLAG in c for c in hook_commands(g))]
    assert "matcher" not in group
    runtime = SCRIPTS_TEMPLATE.format(name=f"{CLIENTS[client].agent}.py")
    assert stops[0].endswith(f'{runtime}" {STOP_CHECK_FLAG}'), stops[0]


def test_a_plugin_with_no_runtime_hook_refuses_to_build() -> None:
    with pytest.raises(ValueError, match="cannot carry the stop check"):
        stop_check.plugin_doc("claude_code", {"hooks": {}}, generic=False)


def _reads(client: str, doc: Any) -> list[str]:
    """The pre-tool commands a Read reaches: entries with no matcher, or one matching `Read`."""
    return [
        c
        for g in _pre_tool_groups(client, doc)
        if not g.get("matcher") or re.fullmatch(g["matcher"], "Read")
        for c in hook_commands(g)
    ]


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private HOME for this process and the hook: the real ~/.chock is never written."""
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("USERPROFILE", str(folder))
    return folder


def _installed(tmp_path: Path, client: str, route: str = "bundle") -> tuple[Path, Path, str]:
    """(project repo, plugin folder, the stop-check command a Read reaches): a bundle, or the shell guard's own package."""
    plugin = tmp_path / f"plugin-{route}"
    members = make_members(tmp_path)
    if route == "bundle":
        write(plugin, merged_files(client, bundle(members), members, tmp_path))
    else:
        [guard] = [m for m in members if m.id == GUARD_ID]
        write(plugin, CLIENTS[client].files(guard.policy_dir, guard.manifest, tmp_path))
    doc = json.loads((plugin / CLIENTS[client].layout()[1]).read_text(encoding="utf-8"))
    [command] = [c for c in _reads(client, doc) if STOP_CHECK_FLAG in c]
    return project(tmp_path), plugin, command


def test_in_claude_only_the_stop_check_reaches_a_read(tmp_path: Path) -> None:
    """The bundle's own policies match the shell and writes alone, so without the stop check a Read ran no hook."""
    [command] = _reads("claude", _hooks("claude", tmp_path))
    assert command.endswith(STOP_CHECK_FLAG)


@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_every_hook_carrying_package_carries_one_stop_check_and_an_advisory_one_none(
    tmp_path: Path, client: str
) -> None:
    """`chock plugin build`'s single-policy packages: the marketplace route, Devin's included."""
    hooks_rel = Path(CLIENTS[client].layout()[1])
    for member in make_members(tmp_path, with_advisory=True):
        files = CLIENTS[client].files(member.policy_dir, member.manifest, tmp_path)
        if member.id == ADVISORY_ID:
            assert hooks_rel not in files
            continue
        if hooks_rel not in files:  # a gate this client cannot run ships nothing
            continue
        stops = [c for c in hook_commands(json.loads(files[hooks_rel])) if STOP_CHECK_FLAG in c]
        assert len(stops) == 1, (member.id, stops)


def _read(repo: Path, plugin: Path, home: Path, command: str, cwd: Path | None = None):
    where = cwd or repo
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": str(where / "notes.txt")},
        "session_id": "s",
        "cwd": str(where),
    }
    env = {k: v for k, v in hook_env(home).items() if k not in PROJECT_DIRS}
    env.update(dict.fromkeys(ALL_ROOTS, plugin.as_posix()))
    return run_hook_command(command, where, json.dumps(payload), env=env)


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def _person_resume(repo: Path) -> int:
    """`chock resume` as a person at a terminal typing the repository's name (a plain call where no terminal is asked)."""
    typed = _Terminal(Path(repo).resolve().name + "\n")
    out = mock.Mock(wraps=sys.stdout, isatty=lambda: True)
    with mock.patch.object(sys, "stdin", typed), mock.patch.object(sys, "stdout", out):
        return chock_stop.resume_main(["--repo", str(repo)])


@pytest.mark.parametrize("route", ["bundle", "package"])
@pytest.mark.parametrize("client", E2E)
def test_a_read_no_policy_matches_is_refused_on_the_plugin_route_while_stopped(
    tmp_path: Path, home: Path, client: str, route: str
) -> None:
    """The e2e: the plugin's real hook command; allowed, stop, refused, resume, allowed."""
    repo, plugin, command = _installed(tmp_path, client, route)
    deny = DENY[client]
    assert deny not in _read(repo, plugin, home, command).stdout
    assert chock_stop.stop_main(["--repo", str(repo), "--reason", "e2e incident"]) == 0
    refused = _read(repo, plugin, home, command)
    assert deny in refused.stdout, (refused.stdout, refused.stderr)
    assert "stopped: e2e incident" in refused.stdout
    assert _person_resume(repo) == 0
    allowed = _read(repo, plugin, home, command)
    assert allowed.returncode == 0, allowed.stderr
    assert deny not in allowed.stdout, allowed.stdout


@pytest.mark.skipif(not hasattr(halt, "halt_registry_entry"), reason="the machine registry arrives with GAP-1c")
@pytest.mark.parametrize("client", E2E)
def test_a_registry_stop_refuses_a_plugin_read_outside_the_stopped_repo(
    tmp_path: Path, home: Path, client: str
) -> None:
    """The registry under the private HOME reaches a plugin call that names no stopped path and no project root."""
    repo, plugin, command = _installed(tmp_path, client, "package")
    outside = tmp_path / "outside"
    outside.mkdir()
    deny = DENY[client]
    assert chock_stop.stop_main(["--repo", str(repo), "--reason", "e2e incident"]) == 0
    assert halt.halt_registry_entry(repo).is_file()
    assert str(halt.halt_registry_entry(repo)).startswith(str(home))
    refused = _read(repo, plugin, home, command, cwd=outside)
    assert deny in refused.stdout, (refused.stdout, refused.stderr)
    assert _person_resume(repo) == 0
    assert deny not in _read(repo, plugin, home, command, cwd=outside).stdout


def _median_ms(run, times: int = 50) -> float:
    taken = []
    for _ in range(times):
        started = time.perf_counter()
        run()
        taken.append((time.perf_counter() - started) * 1000)
    return statistics.median(taken)


def test_plugin_stop_check_latency_unstopped(tmp_path: Path, home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Measured, not asserted against a budget: one bundle's stop check, and three packages' together, per tool call."""
    repo, plugin, command = _installed(tmp_path, "claude")
    one = _median_ms(lambda: _read(repo, plugin, home, command))
    packages = []
    members = [*make_members(tmp_path / "three"), Member(guardrails.protect_dir(), guardrails.protect_manifest())]
    for member in members:
        folder = write(
            tmp_path / "pkg" / member.id, CLIENTS["claude"].files(member.policy_dir, member.manifest, tmp_path)
        )
        doc = json.loads((folder / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        packages += [(folder, c) for c in hook_commands(doc) if STOP_CHECK_FLAG in c]
    assert len(packages) == 3

    def all_three() -> None:
        for folder, stop in packages:
            assert "deny" not in _read(repo, folder, home, stop).stdout

    three = _median_ms(all_three)
    with capsys.disabled():
        print(
            f"\nplugin stop-check unstopped, median of 50 on {sys.platform}: one bundle {one:.1f} ms; three packages {three:.1f} ms total"
        )


def test_without_drops_a_group_its_stop_check_empties_whatever_else_it_holds() -> None:
    check = {"type": "command", "command": f"run {STOP_CHECK_FLAG}"}
    guard = {"matcher": "*", "hooks": [{"type": "command", "command": "guard"}]}
    doc = {"agentseam": {"PreToolUse": [guard, {"matcher": "*", "hooks": [check]}], "Stop": [check]}}
    assert stop_check.without({"matcher": "*", "hooks": [check]}) == {}
    assert stop_check.without(doc) == {"agentseam": {"PreToolUse": [guard]}}

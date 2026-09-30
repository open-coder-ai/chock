"""A hook that cannot read its input, or cannot find its own package, refuses; an ordinary call still passes.

Each plugin client's shipped hook command is run the way the client runs it, single-package and
merged-bundle alike, so a fix in the per-client builder has to reach the bundle to pass.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from bundle_fixtures import ALL_ROOTS, BUNDLE_ID, bundle, hook_commands, make_members, project, write
from conftest import run_hook_command

from chock.plugin.bundle_build import CLIENTS, MERGED, bundle_files

CLIENTS_UNDER_TEST = sorted(name for name, client in CLIENTS.items() if client.route == MERGED)
MALFORMED = ("not json", "", "[1, 2]", '{"tool_name":', "null")


def _payload(client: str, repo: Path, command: str) -> str:
    body: dict = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}
    body["cwd"] = str(repo)
    if client == "cursor":
        envelope = {"conversation_id": "c", "generation_id": "g", "cursor_version": "3.21.18"}
        return json.dumps({**envelope, **body, "hook_event_name": "preToolUse", "workspace_roots": [str(repo)]})
    if client == "devin":
        body["prompt_id"] = "p"
    if client == "copilot":
        body = {**body, "toolName": "bash", "toolArgs": json.dumps({"command": command})}
    return json.dumps(body)


def _refused(proc: object) -> bool:
    out = proc.stdout.lower()
    return proc.returncode == 2 or (proc.returncode == 0 and ('"deny"' in out or '"block"' in out))


def _commands(package: Path) -> list[str]:
    return hook_commands(json.loads(next(package.rglob("hooks.json")).read_text(encoding="utf-8")))


def _run(command: str, repo: Path, payload: str, roots: Path | None) -> object:
    env = {k: v for k, v in os.environ.items() if k not in ALL_ROOTS}
    if roots is not None:
        env.update(dict.fromkeys(ALL_ROOTS, roots.as_posix()))
    return run_hook_command(command, repo, payload, env=env)


@pytest.fixture(params=CLIENTS_UNDER_TEST)
def installed(request, tmp_path: Path) -> tuple[str, Path, Path]:
    client = request.param
    members = make_members(tmp_path)
    package = write(tmp_path / "dist" / client / BUNDLE_ID, bundle_files(client, bundle(members), members, tmp_path))
    return client, package, project(tmp_path)


def test_a_malformed_payload_is_refused(installed) -> None:
    client, package, repo = installed
    for payload in MALFORMED:
        for command in _commands(package):
            done = _run(command, repo, payload, package)
            assert _refused(done), (client, payload, done.returncode, done.stdout, done.stderr)
            assert "could not read" in done.stderr, (client, payload, done.stderr)


def test_an_ordinary_payload_is_still_allowed_and_a_dangerous_one_still_refused(installed) -> None:
    client, package, repo = installed
    ordinary = [_run(c, repo, _payload(client, repo, "ls"), package) for c in _commands(package)]
    assert not any(_refused(done) for done in ordinary), (client, [(d.returncode, d.stdout) for d in ordinary])
    dangerous = [_run(c, repo, _payload(client, repo, "rm -rf /"), package) for c in _commands(package)]
    assert any(_refused(done) for done in dangerous), client


def test_a_hook_that_cannot_find_its_package_refuses(installed) -> None:
    """Only Copilot's command consults a root variable before running; the others fail on the missing file."""
    client, package, repo = installed
    if client != "copilot":
        pytest.skip("only Copilot's hook command tests the plugin root itself")
    for command in _commands(package):
        done = _run(command, repo, _payload(client, repo, "ls"), None)
        assert done.returncode == 2, (done.returncode, done.stdout, done.stderr)
        assert "Refusing" in done.stderr


def test_every_cursor_pre_tool_entry_sets_fail_closed_alone_and_merged(tmp_path: Path) -> None:
    members = make_members(tmp_path)
    packages = [
        bundle_files("cursor", bundle(members), members, tmp_path),
        *(CLIENTS["cursor"].files(m.policy_dir, m.manifest, tmp_path) for m in members),
    ]
    for files in packages:
        doc = json.loads(next(text for rel, text in files.items() if rel.name == "hooks.json"))
        entries = [e for event, group in doc["hooks"].items() if event != "stop" for e in group]
        assert entries
        assert all(entry.get("failClosed") is True for entry in entries), entries

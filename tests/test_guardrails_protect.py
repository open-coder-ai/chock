"""The built-in self-protection: an agent's write to a guardrails toggle file is refused; reads pass."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from guardrails_support import MERGED_CLIENTS, TOGGLE, any_refused, build, shell, write_call

from chock.guardrails.plugin import protect_dir
from chock.plugin import gate_package
from chock.plugin.bundle_build import CLIENTS

IMPL = protect_dir() / "implementations"
GUARD = IMPL / "chock-guardrails-protect.py"
GATE = IMPL / "chock-guardrails-protect-gate.py"
SUITE = protect_dir().parent / "customize-guardrails" / "evals" / "suite.yaml"

WRITES = [
    "echo '{}' > .chock/guardrails.json",
    "echo '{}' >.chock/guardrails.json",
    "printf x >> .chock/guardrails.json",
    "cat a 1> .chock/guardrails.json",
    "tee .chock/guardrails.json < a",
    "cp /tmp/evil.json .chock/guardrails.json",
    "mv x .chock/guardrails.json",
    "sed -i s/on/off/ .chock/guardrails.json",
    "ln -sf /tmp/evil.json .chock/guardrails.json",
    "rm .chock/guardrails.json && cp evil .chock/guardrails.json",
    "echo x > ~/.chock/guardrails.json",
    "echo x > $HOME/.chock/guardrails.json",
    # path tricks: case, doubled slashes, dot segments, backslashes, quoting, globs, braces
    "echo x > .CHOCK/GUARDRAILS.JSON",
    "echo x > .chock//guardrails.json",
    "echo x > .chock/./guardrails.json",
    "echo x > src/../.chock/guardrails.json",
    'echo x > ".chock\\guardrails.json"',
    "echo x > .chock/guard'rails'.json",
    "cp evil .chock/guardrail?.json",
    "cp evil .chock/guardrails.{json,bak}",
    "cd .chock && echo x > guardrails.json",
    "cd .chock\necho x > guardrails.json",
    "python3 -c \"open('.chock/guardrails.json','w').write('x')\"",
    "bash -c 'echo x > .chock/guardrails.json'",
    "echo .chock/guardrails.json | xargs -I{} cp evil {}",
    "F=.chock/guardrails.json; echo x > $F",
    "echo x > $(echo .chock/guardrails.json)",
    "mv /tmp/fake-chock .chock",
    "Set-Content .chock/guardrails.json x",
    "chock bundle off block-destructive-commands",
    "chock bundle on block-destructive-commands --scope user",
    "python -m chock bundle off x",
    "git checkout HEAD -- .chock/guardrails.json",
    # the record `chock bundle` keeps, and its adopt step
    "echo abc > .chock/state/guardrails.sha256",
    "sha256sum .chock/guardrails.json | cut -c1-64 > ~/.chock/state/GUARDRAILS.sha256",
    "rm .chock/state/guardrails.sha256",
    "chock bundle status --adopt",
]
READS = [
    "cat .chock/guardrails.json",
    "jq . .chock/guardrails.json",
    "grep off ~/.chock/guardrails.json",
    "head -n 5 .CHOCK/guardrails.json",
    "git diff -- .chock/guardrails.json",
    "git add .chock/guardrails.json",
    "ls -la .chock",
    "chock bundle status",
    "cat .chock/state/guardrails.sha256",
    "echo x > notes.md",
    "ls -la",
]


def _guard(command: str, cwd: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "CHOCK_RAW_COMMAND": command}
    return subprocess.run(
        [sys.executable, str(GUARD), *command.split()], cwd=cwd, env=env, capture_output=True, text=True, check=False
    )


def _gate(writes: dict[str, str], root: Path, event: str = "pre-tool-use") -> subprocess.CompletedProcess:
    material = json.dumps({"event": event, "repo_root": str(root), "writes": writes})
    return subprocess.run(
        [sys.executable, str(GATE)], cwd=root, input=material, capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize("command", WRITES)
def test_the_shell_guard_refuses_a_write_or_a_switch(tmp_path: Path, command: str) -> None:
    proc = _guard(command, tmp_path)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "may not change .chock/guardrails.json" in proc.stdout


@pytest.mark.parametrize("command", READS)
def test_the_shell_guard_lets_reads_through(tmp_path: Path, command: str) -> None:
    proc = _guard(command, tmp_path)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)


def test_the_shell_guard_follows_a_link_to_the_toggle_file(tmp_path: Path) -> None:
    (tmp_path / ".chock").mkdir()
    (tmp_path / TOGGLE).write_text("{}", encoding="utf-8")
    (tmp_path / "harmless.txt").symlink_to(tmp_path / TOGGLE)
    (tmp_path / "cfg").symlink_to(tmp_path / ".chock")
    assert _guard("echo x > harmless.txt", tmp_path).returncode == 1
    assert _guard("cp evil cfg/GUARDRAILS.json", tmp_path).returncode == 1
    assert _guard("cat harmless.txt", tmp_path).returncode == 0


@pytest.mark.parametrize(
    "path",
    [
        ".chock/guardrails.json",
        ".CHOCK//Guardrails.JSON",
        "./.chock/./guardrails.json",
        "src/../.chock/guardrails.json",
        ".chock\\guardrails.json",
        "nested/repo/.chock/guardrails.json",
        "/home/someone/.chock/guardrails.json",
        "C:\\Users\\someone\\.chock\\guardrails.json",
        ".chock/state/guardrails.sha256",
        "/home/someone/.chock/STATE/guardrails.sha256",
    ],
)
def test_the_write_gate_refuses_every_spelling(tmp_path: Path, path: str) -> None:
    proc = _gate({path: "{}"}, tmp_path)
    assert proc.returncode == 1 and "guardrails toggle file" in proc.stderr


def test_the_write_gate_follows_links_and_passes_other_files(tmp_path: Path) -> None:
    (tmp_path / ".chock").mkdir()
    (tmp_path / TOGGLE).write_text("{}", encoding="utf-8")
    (tmp_path / "alias.json").symlink_to(tmp_path / TOGGLE)
    (tmp_path / "dir").symlink_to(tmp_path / ".chock")
    assert _gate({"alias.json": "{}"}, tmp_path).returncode == 1
    assert _gate({"dir/guardrails.json": "{}"}, tmp_path).returncode == 1
    assert _gate({"src/guardrails.json.md": "x", ".chock/config.yaml": "x", "notes.md": "x"}, tmp_path).returncode == 0


def test_the_write_gate_never_refuses_the_persons_own_change_at_turn_end(tmp_path: Path) -> None:
    assert _gate({TOGGLE: "{}"}, tmp_path, event="stop").returncode == 0


@pytest.mark.parametrize("client", MERGED_CLIENTS)
def test_every_merged_plugin_refuses_the_agents_write(tmp_path: Path, client: str) -> None:
    plugin, repo, commands = build(tmp_path, client)
    home = tmp_path / "home"
    home.mkdir()
    for command in ("echo '{}' > .chock/guardrails.json", "chock bundle off demo-shell-guard"):
        assert any_refused(commands, plugin, repo, shell(client, repo, command), home), command
    assert not any_refused(commands, plugin, repo, shell(client, repo, "cat .chock/guardrails.json"), home)


@pytest.mark.parametrize("client", MERGED_CLIENTS)
def test_every_merged_plugin_refuses_an_edit_or_write_where_the_client_judges_writes(
    tmp_path: Path, client: str
) -> None:
    plugin, repo, commands = build(tmp_path, client)
    home = tmp_path / "home"
    home.mkdir()
    clean = write_call(client, repo, str(repo / "notes.md"), "hello")
    assert not any_refused(commands, plugin, repo, clean, home)
    toggle_write = write_call(client, repo, str(repo / ".CHOCK" / "guardrails.json"), "{}")
    user_write = write_call(client, repo, str(home / ".chock" / "guardrails.json"), "{}")
    if gate_package.gate_reach(CLIENTS[client].agent)[0] is None:
        pytest.skip(f"{client}: no write-tool vocabulary, so no write is judged; the shell guard is its protection")
    assert any_refused(commands, plugin, repo, toggle_write, home)
    assert any_refused(commands, plugin, repo, user_write, home)


def _cases() -> list[dict]:
    cases = yaml.safe_load(SUITE.read_text(encoding="utf-8"))["suite"]["cases"]
    return [c for c in cases if c.get("execute")]


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["id"])
def test_the_skills_executable_eval_cases_replay(tmp_path: Path, case: dict) -> None:
    run = case["execute"]
    proc = _guard(run["command"], tmp_path) if "command" in run else _gate(run["writes"], tmp_path)
    assert (proc.returncode == 1) is (run["expect"] == "block"), (case["id"], proc.stdout, proc.stderr)

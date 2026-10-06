"""The built-in self-protection refuses an agent's `chock install --trust-local` and its write to an install marker."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from guardrails_support import MERGED_CLIENTS, any_refused, build, shell, write_call

from chock.guardrails.plugin import protect_dir
from chock.install import cli
from chock.plugin import gate_package
from chock.plugin.bundle_build import CLIENTS

IMPL = protect_dir() / "implementations"
GUARD = IMPL / "chock-guardrails-protect.py"
GATE = IMPL / "chock-guardrails-protect-gate.py"
SHA = "a" * 64
MARKER = "chock.selection.json"
TRUSTING = [
    f"chock install --selection sel.yaml --trust-local my-x={SHA}",
    f"chock install --selection sel.yaml --trust-local=my-x={SHA}",
    f"chock install --selection sel.yaml --trust my-x={SHA}",
    f"chock install --selection sel.yaml --trust-l=my-x={SHA}",
    f"chock install --selection sel.yaml --TRUST-LOCAL my-x={SHA}",
    f"/usr/local/bin/chock install --selection sel.yaml --trust-local my-x={SHA}",
    f"python -m chock install --selection sel.yaml --trust-local my-x={SHA}",
    f"python3 -m chock.install.cli --selection sel.yaml --trust-local my-x={SHA}",
    f"cd mine && chock install --selection sel.yaml --trust-local my-x={SHA}",
    f"bash -c 'chock install --selection sel.yaml --trust-local my-x={SHA}'",
    f"T=--trust-local; chock install --selection sel.yaml $T my-x={SHA}",
]
MARKER_WRITES = [
    f"echo '{{}}' > ~/.chock/marketplace/claude-code/claude/mine/{MARKER}",
    f"cp evil.json ~/.chock/marketplace/claude-code/claude/mine/{MARKER}",
    f"sed -i s/old/new/ plugin/{MARKER}",
    f"tee plugin/{MARKER.upper()} < evil.json",
    f"python3 -c \"open('plugin/{MARKER}','w').write('x')\"",
    "cp evil.json plugin/chock.selection.*",
]
ALLOWED = [
    "chock install --selection sel.yaml",
    "chock install --selection sel.yaml --client cursor --apply",
    f"cat ~/.chock/marketplace/claude-code/claude/mine/{MARKER}",
    f"jq .marker plugin/{MARKER}",
    "grep -rn -- --trust-local docs/",
    "chock new policy tf --kind guard",
]


def _guard(command: str, cwd: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "CHOCK_RAW_COMMAND": command}
    return subprocess.run(
        [sys.executable, str(GUARD), *command.split()], cwd=cwd, env=env, capture_output=True, text=True, check=False
    )


def _gate(writes: dict[str, str], root: Path) -> subprocess.CompletedProcess:
    material = json.dumps({"event": "pre-tool-use", "repo_root": str(root), "writes": writes})
    return subprocess.run(
        [sys.executable, str(GATE)], cwd=root, input=material, capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize("command", TRUSTING + MARKER_WRITES)
def test_the_shell_guard_refuses_trust_local_and_marker_writes(tmp_path: Path, command: str) -> None:
    proc = _guard(command, tmp_path)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "may not accept custom policy code for a person" in proc.stdout
    assert "`chock install --selection <file> --trust-local <id>=<sha256>`" in proc.stdout


@pytest.mark.parametrize("command", ALLOWED)
def test_a_plain_install_and_marker_reads_pass(tmp_path: Path, command: str) -> None:
    proc = _guard(command, tmp_path)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)


def test_a_marker_reached_through_a_link_is_refused(tmp_path: Path) -> None:
    (tmp_path / MARKER).write_text("{}", encoding="utf-8")
    (tmp_path / "harmless.json").symlink_to(tmp_path / MARKER)
    assert _guard("echo x > harmless.json", tmp_path).returncode == 1
    assert _gate({"harmless.json": "{}"}, tmp_path).returncode == 1
    assert _guard("cat harmless.json", tmp_path).returncode == 0


@pytest.mark.parametrize(
    "path", [MARKER, f"/home/someone/.chock/marketplace/codex/codex/mine/{MARKER}", "plugin\\CHOCK.SELECTION.JSON"]
)
def test_the_write_gate_refuses_a_marker_write(tmp_path: Path, path: str) -> None:
    proc = _gate({path: "{}"}, tmp_path)
    assert proc.returncode == 1
    assert f"{path}: install marker" in proc.stderr
    assert "--trust-local <id>=<sha256>" in proc.stderr


def test_the_write_gate_passes_the_selection_file_and_other_json(tmp_path: Path) -> None:
    assert _gate({"chock.selection.yaml": "x", "selection.json": "{}", "notes.md": "x"}, tmp_path).returncode == 0


@pytest.mark.parametrize("flag", ["--trust", "--trust-l", "--trust-loc"])
def test_install_takes_no_abbreviation_of_trust_local(flag: str, capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--selection", "sel.yaml", flag, f"my-x={SHA}"])
    assert raised.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


@pytest.mark.parametrize("client", MERGED_CLIENTS)
def test_every_merged_plugin_refuses_the_agents_trust_local(tmp_path: Path, client: str) -> None:
    plugin, repo, commands = build(tmp_path, client)
    home = tmp_path / "home"
    home.mkdir()
    assert any_refused(commands, plugin, repo, shell(client, repo, TRUSTING[0]), home)
    assert not any_refused(commands, plugin, repo, shell(client, repo, ALLOWED[0]), home)
    if gate_package.gate_reach(CLIENTS[client].agent)[0] is not None:
        marker_write = write_call(client, repo, str(home / ".chock" / "marketplace" / MARKER), "{}")
        assert any_refused(commands, plugin, repo, marker_write, home)

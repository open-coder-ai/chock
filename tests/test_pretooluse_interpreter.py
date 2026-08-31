"""The PreToolUse guard must run even where a bare `python` is not on PATH."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from conftest import baseline_policy

from chock.compile.compiler import compile_policy
from chock.compile.surfaces import Surface
from chock.hooks.pretooluse_install import (
    INTERPRETER_PLACEHOLDER,
    install_pretooluse_hooks,
    installed_pretooluse_policy_ids,
)

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]


def _fresh_repo() -> tuple[Path, dict]:
    import shutil

    repo = Path(tempfile.mkdtemp()) / "r"
    repo.mkdir()
    env = {**os.environ, "PYTHONPATH": str(FRAMEWORK_ROOT / "src")}
    subprocess.run(["git", "init", "-q", "."], cwd=repo, check=True)
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "init", ".", "--skip-hooks"], cwd=repo, capture_output=True, env=env
    )
    shutil.copytree(
        baseline_policy("block-destructive-commands"), repo / ".agents" / "policies" / "block-destructive-commands"
    )
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "recompile", "--skip-hooks", "--repo", str(repo)],
        cwd=repo,
        capture_output=True,
        env=env,
    )
    return repo, env


def _payload(command: str) -> str:
    return json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "hook_event_name": "PreToolUse",
            "session_id": "s",
            "transcript_path": "/t",
            "permission_mode": "default",
        }
    )


def test_compiled_fragment_keeps_the_placeholder(tmp_path: Path) -> None:
    policy = baseline_policy("block-destructive-commands")
    out = tmp_path / ".chock" / "compiled"
    compile_policy(policy, targets=[Surface.PRE_TOOL_USE.value], output_root=out, agents=["claude"])
    frag = json.loads((out / "block-destructive-commands" / "pre-tool-use" / "pretooluse.json").read_text())
    command = frag["hooks"][0]["command"]
    assert INTERPRETER_PLACEHOLDER in command
    assert not command.startswith("python ")


def test_installed_command_bakes_a_real_interpreter() -> None:
    repo, _ = _fresh_repo()
    install_pretooluse_hooks(repo)
    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert INTERPRETER_PLACEHOLDER not in command, "install must substitute the placeholder"
    assert sys.executable in command


def test_guard_blocks_even_with_no_python_on_path() -> None:
    repo, _ = _fresh_repo()
    install_pretooluse_hooks(repo)
    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"].replace("${CLAUDE_PROJECT_DIR}", str(repo))
    stripped = {k: v for k, v in os.environ.items() if k != "PATH"}
    stripped["PATH"] = ""
    stripped["CLAUDE_PROJECT_DIR"] = str(repo)
    proc = subprocess.run(
        command, cwd=repo, shell=True, env=stripped, capture_output=True, text=True, input=_payload("rm -rf /")
    )
    assert proc.returncode == 0, f"guard errored with PATH stripped:\n{proc.stdout}{proc.stderr}"
    decision = json.loads(proc.stdout)
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny", (
        f"guard did not block with PATH stripped:\n{proc.stdout}{proc.stderr}"
    )


def test_coverage_detection_survives_the_bake() -> None:
    repo, _ = _fresh_repo()
    install_pretooluse_hooks(repo)
    assert "block-destructive-commands" in installed_pretooluse_policy_ids(repo)


def _rewrite_interpreter(repo: Path, token: str) -> None:
    settings_path = repo / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    for entry in settings["hooks"]["PreToolUse"]:
        for hook in entry["hooks"]:
            command = hook["command"]
            hook["command"] = token + command[command.index(' "') :]
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def test_coverage_is_machine_independent() -> None:
    repo, _ = _fresh_repo()
    install_pretooluse_hooks(repo)
    for token in ('"/usr/bin/python3.12"', "python"):
        _rewrite_interpreter(repo, token)
        assert "block-destructive-commands" in installed_pretooluse_policy_ids(repo), token


def _fake_but_real_interpreter(tmp_path: Path) -> str:
    """A path that is not `sys.executable` but genuinely resolves on this machine."""
    import shutil

    fake = tmp_path / "another-machine-python3"
    shutil.copy(sys.executable, fake)
    fake.chmod(0o755)
    return str(fake)


def test_reinstall_does_not_churn_a_committed_entry(tmp_path: Path) -> None:
    repo, _ = _fresh_repo()
    install_pretooluse_hooks(repo)
    other = _fake_but_real_interpreter(tmp_path)
    _rewrite_interpreter(repo, f'"{other}"')
    before = (repo / ".claude" / "settings.json").read_text(encoding="utf-8")
    install_pretooluse_hooks(repo)
    after = (repo / ".claude" / "settings.json").read_text(encoding="utf-8")
    assert json.loads(after) == json.loads(before), "an equivalent, still-runnable installed entry was re-baked"


def test_reinstall_rebakes_an_interpreter_that_no_longer_resolves() -> None:
    repo, _ = _fresh_repo()
    install_pretooluse_hooks(repo)
    _rewrite_interpreter(repo, '"/usr/local/bin/definitely-not-a-real-interpreter3"')
    install_pretooluse_hooks(repo)
    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert sys.executable in command, "a dead interpreter path must be rebaked to one that runs here"

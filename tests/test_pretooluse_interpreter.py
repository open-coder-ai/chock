"""The PreToolUse guard must run even where a bare `python` is not on PATH.

On a python3-only system the emitted command `python ...` exited 127; Claude Code treats
any non-2 exit as non-blocking, so the guard allowed everything while coverage -- keyed on
the fragment being installed -- still reported `enforced`. Install now bakes the running
interpreter (an absolute path, shell-agnostic) into settings.json, while the compiled
fragment keeps a placeholder so committed compiled output stays portable.
"""

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
    # Committed compiled output must be portable: no machine-specific interpreter in it.
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
    # The python3-only regression: strip PATH so neither `python` nor `python3` resolve.
    # The baked absolute interpreter must still run the guard and deny. Claude Code's deny
    # rides entirely in the JSON body on a clean exit (see agentseam's claude_code.respond()
    # docstring for why exit 2 is deliberately not used), not the exit code.
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
    # settings.json holds the baked command; the compiled fragment holds the placeholder.
    # installed_pretooluse_policy_ids must still recognise the fragment as installed.
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
    # settings.json may be COMMITTED (the catalog commits it), so the verdict must not
    # depend on whose interpreter is baked in. Another machine's path and the historic
    # bare `python` must both still count as installed.
    repo, _ = _fresh_repo()
    install_pretooluse_hooks(repo)
    for token in ('"/usr/bin/python3.12"', "python"):
        _rewrite_interpreter(repo, token)
        assert "block-destructive-commands" in installed_pretooluse_policy_ids(repo), token


def test_reinstall_does_not_churn_a_committed_entry() -> None:
    # A sync on a second machine must not rewrite an equivalent installed entry with its
    # own interpreter path -- that is diff churn in a committed file, and a leaked path.
    repo, _ = _fresh_repo()
    install_pretooluse_hooks(repo)
    _rewrite_interpreter(repo, '"/usr/bin/python3.12"')
    before = (repo / ".claude" / "settings.json").read_text(encoding="utf-8")
    install_pretooluse_hooks(repo)
    after = (repo / ".claude" / "settings.json").read_text(encoding="utf-8")
    assert json.loads(after) == json.loads(before), "an equivalent installed entry was re-baked"

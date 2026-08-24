"""PreToolUse enforcement: the adapter, the installer, and the end-to-end path.

`compile` emitted PreToolUse fragments that nothing installed, in a shape Claude Code would
never have read, invoking guards that read argv while Claude sends JSON on stdin. Three
independent breaks, and `coverage.json` reported the policies as `enforced` throughout.

Wiring up the installer alone would have been *worse* than leaving it: the hooks would fire,
the guards would receive no arguments, every destructive command would be allowed, and the
enforcement claim would finally have looked justified.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from conftest import baseline_policy

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = FRAMEWORK_ROOT / "src" / "chock" / "gate" / "pretooluse.py"
GUARD = baseline_policy("block-destructive-commands") / "implementations" / "block-destructive.sh"


def _payload(command: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


def _adapter(command: str, guard: Path = GUARD) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ADAPTER), "--guard", str(guard)],
        input=_payload(command),
        capture_output=True,
        text=True,
    )


# ----------------------------------------------------------------- the adapter contract
@pytest.mark.parametrize(
    "command",
    ["rm -rf /", "git push --force origin main", "git reset --hard HEAD~1"],
)
def test_dangerous_commands_block(command: str) -> None:
    """Exit 2 is what Claude Code treats as a block."""
    result = _adapter(command)
    assert result.returncode == 2, f"{command!r} was allowed:\n{result.stdout}{result.stderr}"
    assert "BLOCKED" in result.stderr


@pytest.mark.parametrize("command", ["ls -la", "git push --force-with-lease origin main", "git status"])
def test_safe_commands_are_allowed(command: str) -> None:
    assert _adapter(command).returncode == 0


def test_argv_guard_receives_the_stdin_command() -> None:
    """The original defect: guards read argv, Claude sends JSON on stdin.

    Invoking the guard directly with no argv -- which is what an installed hook would have
    done before the adapter existed -- allows `rm -rf /`.
    """
    sys.path.insert(0, str(ADAPTER.parent))
    from pretooluse import find_bash  # the same resolver the adapter uses

    bash = find_bash(GUARD)
    assert bash, "no usable bash on this machine; cannot exercise the guard"
    direct = subprocess.run([bash, str(GUARD)], input=_payload("rm -rf /"), capture_output=True, text=True)
    assert direct.returncode == 0, "precondition: the bare guard ignores stdin"
    assert _adapter("rm -rf /").returncode == 2, "the adapter must bridge stdin to argv"


def test_unparseable_input_allows_and_says_so() -> None:
    """Failing closed here would block every Bash call on a malformed payload."""
    result = subprocess.run(
        [sys.executable, str(ADAPTER), "--guard", str(GUARD)],
        input="not json",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "not checked" in result.stderr


def test_missing_guard_allows_and_says_so(tmp_path: Path) -> None:
    result = _adapter("rm -rf /", guard=tmp_path / "absent.sh")
    assert result.returncode == 0
    assert "not checked" in result.stderr


def test_non_command_tool_input_is_ignored() -> None:
    result = subprocess.run(
        [sys.executable, str(ADAPTER), "--guard", str(GUARD)],
        input=json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}}),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


# ------------------------------------------------------------------------- the installer
def _fresh_repo() -> tuple[Path, dict]:
    """A scaffolded repo holding the two policies that compile a PreToolUse guard.

    `init` installs no policies, so they are copied in explicitly -- the same
    copy-a-folder step an adopter takes. Without them there is nothing to install and the
    installer would be asserted against an empty input.
    """
    import shutil

    repo = Path(tempfile.mkdtemp()) / "r"
    repo.mkdir()
    env = {**os.environ, "PYTHONPATH": str(FRAMEWORK_ROOT / "src")}
    subprocess.run(["git", "init", "-q", "."], cwd=repo, check=True)
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "init", ".", "--skip-hooks"],
        cwd=repo,
        capture_output=True,
        env=env,
    )
    for policy_id in ("block-destructive-commands", "block-no-verify"):
        shutil.copytree(baseline_policy(policy_id), repo / ".agents" / "policies" / policy_id)
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "recompile", "--skip-hooks", "--repo", str(repo)],
        cwd=repo,
        capture_output=True,
        env=env,
    )
    return repo, env


def test_install_writes_claude_settings_schema() -> None:
    from chock.hooks.pretooluse_install import install_pretooluse_hooks

    repo, env = _fresh_repo()
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "recompile", "--skip-hooks", "--repo", str(repo)],
        cwd=repo,
        capture_output=True,
        env=env,
    )
    install_pretooluse_hooks(repo)

    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    entries = settings["hooks"]["PreToolUse"]
    assert entries, "no PreToolUse entries installed"
    for entry in entries:
        assert entry["matcher"] == "Bash"
        hook = entry["hooks"][0]
        assert hook["type"] == "command"
        assert "${CLAUDE_PROJECT_DIR}" in hook["command"], "paths must survive a repo move"
    assert (repo / ".chock" / "bin" / "pretooluse.py").exists()


def test_install_preserves_unrelated_settings() -> None:
    """The settings file is the adopter's; only our own entries may be rewritten."""
    from chock.hooks.pretooluse_install import install_pretooluse_hooks

    repo, env = _fresh_repo()
    settings_path = repo / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Bash(ls *)"]},
                "hooks": {
                    "PreToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command": "mine.sh"}]}],
                    "PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "after.sh"}]}],
                },
            }
        ),
        encoding="utf-8",
    )
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "recompile", "--skip-hooks", "--repo", str(repo)],
        cwd=repo,
        capture_output=True,
        env=env,
    )
    install_pretooluse_hooks(repo)

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["permissions"] == {"allow": ["Bash(ls *)"]}
    assert settings["hooks"]["PostToolUse"][0]["hooks"][0]["command"] == "after.sh"
    commands = [h["command"] for e in settings["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert "mine.sh" in commands, "a hand-written PreToolUse hook was discarded"


def test_reinstall_is_idempotent() -> None:
    from chock.hooks.pretooluse_install import install_pretooluse_hooks

    repo, env = _fresh_repo()
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "recompile", "--skip-hooks", "--repo", str(repo)],
        cwd=repo,
        capture_output=True,
        env=env,
    )
    install_pretooluse_hooks(repo)
    first = (repo / ".claude" / "settings.json").read_text(encoding="utf-8")
    install_pretooluse_hooks(repo)
    assert (repo / ".claude" / "settings.json").read_text(encoding="utf-8") == first


def test_removing_the_fragments_removes_the_hooks() -> None:
    """A disabled or deleted policy must stop enforcing."""
    import shutil as sh

    from chock.hooks.pretooluse_install import install_pretooluse_hooks

    repo, env = _fresh_repo()
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "recompile", "--skip-hooks", "--repo", str(repo)],
        cwd=repo,
        capture_output=True,
        env=env,
    )
    install_pretooluse_hooks(repo)
    for path in (repo / ".chock" / "compiled").glob("*/pre-tool-use"):
        sh.rmtree(path)
    install_pretooluse_hooks(repo)

    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert not settings.get("hooks", {}).get("PreToolUse")
    assert not (repo / ".chock" / "bin" / "pretooluse.py").exists()


def test_end_to_end_installed_hooks_block_real_commands() -> None:
    """The acceptance test: run what Claude Code runs, from a real `install-hooks`."""
    repo, env = _fresh_repo()
    subprocess.run([sys.executable, "-m", "chock.cli", "install-hooks", "."], cwd=repo, capture_output=True, env=env)
    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    entries = settings["hooks"]["PreToolUse"]
    env = {**env, "CLAUDE_PROJECT_DIR": str(repo)}

    def blocked(command: str) -> bool:
        for entry in entries:
            cmd = entry["hooks"][0]["command"].replace("${CLAUDE_PROJECT_DIR}", str(repo))
            proc = subprocess.run(
                cmd, cwd=repo, shell=True, env=env, capture_output=True, text=True, input=_payload(command)
            )
            if proc.returncode == 2:
                return True
        return False

    assert blocked("rm -rf /")
    assert blocked("git push --force origin main")
    assert blocked("git commit --no-verify -m x")
    assert not blocked("git push --force-with-lease origin main")
    assert not blocked("ls -la")

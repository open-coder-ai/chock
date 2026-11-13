"""`chock emit --managed claude_code`: the emitted hooks run as stated, the guard refuses system paths, refusals are clean."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from managed_emit_helpers import (
    bundle_hook,
    drop_in,
    env_for,
    handlers,
    linux,
    make_repo,
    one_line_refusal,
    plan_of,
    run_hook,
)

from chock.compile.emitters import managed
from chock.compile.emitters.managed import claude_code


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path)


def test_the_bundle_runs_on_its_own(repo: Path, tmp_path: Path) -> None:
    """The emitted handler, rooted at the bundle itself, refuses the canary and allows a harmless call."""
    _, hook = bundle_hook(repo, tmp_path)
    env = env_for(tmp_path)
    denied, allowed = (
        run_hook(hook, "git commit --no-verify -m x", tmp_path, env),
        run_hook(hook, "git status", tmp_path, env),
    )
    assert denied.returncode == allowed.returncode == 0, denied.stderr + allowed.stderr
    assert '"permissionDecision": "deny"' in denied.stdout
    assert "deny" not in allowed.stdout


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("git"), reason="POSIX stubs and git config")
def test_user_interpreter_settings_do_not_switch_the_hook_off(repo: Path, tmp_path: Path) -> None:
    """Finding 1: chock.python set to a stub (local and global) and stub python3, python, sh, git first on PATH."""
    _, hook = bundle_hook(repo, tmp_path)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name in ("python3", "python", "py", "sh", "git"):
        stub = stubs / name
        stub.write_text("#!/bin/sh\nprintf chock-python >&9 2>/dev/null; exit 0\n", encoding="utf-8")
        stub.chmod(0o755)
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "config", "chock.python", str(stubs / "python3")], check=True)
    global_config = tmp_path / "gitconfig"
    global_config.write_text(f"[chock]\n\tpython = {stubs / 'python3'}\n", encoding="utf-8")
    env = env_for(
        tmp_path,
        PATH=f"{stubs}{os.pathsep}{os.environ.get('PATH', '')}",
        GIT_CONFIG_GLOBAL=str(global_config),
        PYTHONPATH=str(stubs),
        PYTHONSTARTUP=str(stubs / "python3"),
    )
    for cwd in (work, tmp_path):
        done = run_hook(hook, "git commit --no-verify -m x", cwd, env)
        assert done.returncode == 0, done.stderr
        assert '"permissionDecision": "deny"' in done.stdout


@pytest.mark.parametrize(("choice", "code"), [("block", 2), ("allow", 0)])
def test_a_missing_bundle_file_follows_on_failure(repo: Path, tmp_path: Path, choice: str, code: int) -> None:
    """Ruling 2: block refuses (exit 2) and allow lets the call through, each with a note on stderr."""
    bundle, hook = bundle_hook(repo, tmp_path, on_failure=choice)
    (bundle / "block-no-verify" / "scripts" / "_chock_runtime.py").unlink()
    done = run_hook(hook, "git status", tmp_path, env_for(tmp_path))
    assert done.returncode == code
    assert done.stderr.startswith("chock: missing ") and f"--on-failure {choice}" in done.stderr
    assert done.stdout == ""


@pytest.mark.parametrize(("choice", "code"), [("block", 2), ("allow", 0)])
def test_too_old_a_python_follows_on_failure(choice: str, code: int) -> None:
    """Ruling 2: the version check runs before any runtime code; here the minimum is raised past this Python."""
    program = claude_code.bootstrap(choice).replace("(3, 11,)", "(99,)")
    done = subprocess.run(
        [sys.executable, "-I", "-c", program, __file__], capture_output=True, text=True, check=False, timeout=60
    )
    assert done.returncode == code
    assert "this hook needs Python" in done.stderr and f"--on-failure {choice}" in done.stderr


def test_the_stop_gate_never_refuses_for_a_missing_runtime(repo: Path, tmp_path: Path) -> None:
    """onFailure has no effect on Stop, and exit 2 there sends Claude back to work: the turn-end gate notes and exits 0."""
    assert linux(repo, tmp_path / "out", "--policies", "scan-secrets") == 0
    stop = [hook for event, hook in handlers(drop_in(tmp_path / "out")) if event == "Stop"]
    assert stop and all("sys.exit(0)" in hook["args"][4] for hook in stop)


@pytest.mark.parametrize(
    ("path", "platform"),
    [
        ("/", "linux"),
        ("//etc/x", "linux"),
        ("/var/lib/x", "linux"),
        ("/srv/x", "linux"),
        ("/root/x", "linux"),
        ("/run/x", "linux"),
        ("/sys/x", "linux"),
        ("/proc/x", "linux"),
        ("/", "macos"),
        ("/LIBRARY/Application Support/ClaudeCode/x", "macos"),
        ("/system/x", "macos"),
        ("/private/etc/x", "macos"),
        ("C:/", "windows"),
        ("D:\\", "windows"),
        ("c:\\program files\\ClaudeCode", "windows"),
        ("\\\\?\\C:\\Program Files\\x", "windows"),
        ("\\\\.\\C:\\Windows\\x", "windows"),
        ("\\\\localhost\\C$\\Program Files\\x", "windows"),
        ("\\\\?\\UNC\\server\\c$\\Windows", "windows"),
    ],
)
def test_every_system_spelling_is_refused(path: str, platform: str) -> None:
    """Finding 4: filesystem roots, the listed trees, case-insensitive spellings, device and admin-share prefixes."""
    assert managed.root_named(path, platform) is not None


@pytest.mark.parametrize(
    ("path", "platform"),
    [("/home/me/out", "linux"), ("/tmp/out", "linux"), ("/Users/me/out", "macos"), ("C:/Users/me/out", "windows")],
)
def test_ordinary_folders_are_allowed(path: str, platform: str) -> None:
    assert managed.root_named(path, platform) is None


def test_out_naming_a_file_is_refused_cleanly(repo: Path, tmp_path: Path, capsys) -> None:
    """Finding 5."""
    afile = tmp_path / "afile"
    afile.write_text("x", encoding="utf-8")
    assert linux(repo, afile) == 1
    assert "is not a folder" in one_line_refusal(capsys)
    assert afile.read_text(encoding="utf-8") == "x"


@pytest.mark.parametrize("name", ["manifest.yaml", "block-no-verify.py"])
def test_a_non_utf8_policy_file_is_refused_cleanly(repo: Path, tmp_path: Path, name: str, capsys) -> None:
    """Finding 5: a non-UTF-8 manifest or guard."""
    [target] = list((repo / ".agents" / "policies" / "block-no-verify").rglob(name))
    target.write_bytes(target.read_bytes() + b"\xe9\n")
    assert linux(repo, tmp_path / "out", "--policies", "block-no-verify") == 1
    assert "is not UTF-8 text" in one_line_refusal(capsys)
    assert not (tmp_path / "out").exists()


def test_a_missing_repo_is_refused_cleanly(tmp_path: Path, capsys) -> None:
    """Findings 5, 9: says the folder is missing, not that no policy has a guard."""
    assert linux(tmp_path / "does-not-exist", tmp_path / "out") == 1
    assert "is not a folder" in one_line_refusal(capsys)


def test_deploy_json_states_ownership_stop_file_and_lock_effects(repo: Path, tmp_path: Path) -> None:
    """Ruling 6 (findings 7, 9): admin-owned bundle with the vendor's words, the repo stop, every --lock side effect."""
    assert linux(repo, tmp_path / "out", "--lock") == 0
    plan = plan_of(tmp_path / "out")
    text = json.dumps(plan)
    assert any("owned by an administrator and not writable by users" in line for line in plan["requirements"])
    assert "can edit the managed source itself" in text
    assert any(".chock/stop.json" in line and "refuse every tool call" in line for line in plan["caveats"])
    lock = plan["notes"][-1]
    for effect in (
        "user, project and local hooks",
        "hooks in agent frontmatter",
        "monitors of other plugins",
        "command source are disabled",
        "headersHelper",
        "status line and file suggestion",
        "/goal",
        "force-enable",
    ):
        assert effect in lock, effect


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("git"), reason="POSIX paths, a git repository")
def test_a_repo_stop_file_refuses_matched_calls_as_deploy_json_says(repo: Path, tmp_path: Path) -> None:
    """Finding 7: the behaviour the caveat states, proven."""
    _, hook = bundle_hook(repo, tmp_path)
    work = tmp_path / "stopped"
    (work / ".chock").mkdir(parents=True)
    (work / ".chock" / "stop.json").write_text("not json", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    done = run_hook(hook, "ls", work, env_for(tmp_path))
    assert done.returncode == 0 and '"permissionDecision": "deny"' in done.stdout

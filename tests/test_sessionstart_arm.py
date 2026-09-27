"""The SessionStart arm hook: a fresh clone's gap between "rules visible" and "gates armed"."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from chock.gate import runtime_bundle
from chock.hooks.launch import LAUNCHER_REL, hook_command
from chock.hooks.sessionstart_install import install_sessionstart_hook

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]

SESSION_START_PAYLOAD = json.dumps(
    {
        "hook_event_name": "SessionStart",
        "session_id": "s",
        "transcript_path": "/t",
        "permission_mode": "default",
    }
)


def _rendered_runtime(tmp_path: Path) -> Path:
    path = tmp_path / "claude_code.py"
    path.write_text(runtime_bundle.render("claude_code"), encoding="utf-8")
    return path


def _bare_repo() -> Path:
    repo = Path(tempfile.mkdtemp()) / "r"
    (repo / ".chock").mkdir(parents=True)
    return repo


def _settings(repo: Path) -> dict:
    return json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))


def _entry_command(settings: dict) -> str:
    return settings["hooks"]["SessionStart"][-1]["hooks"][0]["command"]


def test_install_writes_the_launcher_form_and_vendors_runtime() -> None:
    repo = _bare_repo()
    assert install_sessionstart_hook(repo) is True
    command = _entry_command(_settings(repo))
    assert command == hook_command(".chock/bin/claude_code.py")
    assert sys.executable not in command, "no interpreter path may be committed"
    assert "${" not in command
    vendored = repo / ".chock" / "bin" / "claude_code.py"
    assert vendored.read_text(encoding="utf-8") == runtime_bundle.render("claude_code"), (
        "vendored copy must match the render exactly"
    )
    assert (repo / LAUNCHER_REL).is_file(), "the arm command runs through the launcher"


def test_reinstall_is_a_no_op() -> None:
    repo = _bare_repo()
    install_sessionstart_hook(repo)
    before = (repo / ".claude" / "settings.json").read_bytes()
    assert install_sessionstart_hook(repo) is False
    assert (repo / ".claude" / "settings.json").read_bytes() == before


def test_adopter_sessionstart_entries_survive() -> None:
    repo = _bare_repo()
    settings_path = repo / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    theirs = {"hooks": [{"type": "command", "command": "echo hello"}]}
    settings_path.write_text(json.dumps({"hooks": {"SessionStart": [theirs]}}), encoding="utf-8")
    install_sessionstart_hook(repo)
    entries = _settings(repo)["hooks"]["SessionStart"]
    assert entries[0] == theirs, "the adopter's own entry must survive, first"
    assert len(entries) == 2


def test_reinstall_on_another_machine_is_a_no_op(monkeypatch) -> None:
    """Nothing machine-specific is written, so a different interpreter changes nothing."""
    repo = _bare_repo()
    install_sessionstart_hook(repo)
    before = (repo / ".claude" / "settings.json").read_bytes()
    monkeypatch.setattr(sys, "executable", "/opt/elsewhere/bin/python3")
    assert install_sessionstart_hook(repo) is False
    assert (repo / ".claude" / "settings.json").read_bytes() == before


def test_an_old_baked_entry_is_replaced_and_foreign_entries_kept() -> None:
    repo = _bare_repo()
    settings_path = repo / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    theirs = {"hooks": [{"type": "command", "command": "echo hello"}]}
    old = {
        "hooks": [
            {
                "type": "command",
                "command": '"/usr/bin/python3" "${CLAUDE_PROJECT_DIR}/.chock/bin/claude_code.py"',
                "timeout": 300,
            }
        ]
    }
    settings_path.write_text(json.dumps({"hooks": {"SessionStart": [theirs, old]}}), encoding="utf-8")
    assert install_sessionstart_hook(repo) is True
    entries = _settings(repo)["hooks"]["SessionStart"]
    assert entries[0] == theirs
    assert len(entries) == 2, "the old entry is recognised as ours and replaced, not duplicated"
    assert entries[1]["hooks"][0]["command"] == hook_command(".chock/bin/claude_code.py")


def _load_runtime(path: Path):
    spec = importlib.util.spec_from_file_location("chock_claude_code_runtime", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_runtime(path: Path, cwd: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(cwd), **(extra_env or {})}
    return subprocess.run(
        [sys.executable, str(path)], cwd=cwd, env=env, input=SESSION_START_PAYLOAD, capture_output=True, text=True
    )


def test_adapter_is_silent_outside_a_chock_repo(tmp_path: Path) -> None:
    runtime = _rendered_runtime(tmp_path)
    proc = _run_runtime(runtime, tmp_path)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_adapter_is_silent_when_already_armed(tmp_path: Path) -> None:
    runtime = _rendered_runtime(tmp_path)
    repo = tmp_path / "r"
    (repo / ".chock").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "."], cwd=repo, check=True)
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-commit").write_text("#!/bin/sh\n# Generated by Chock\n", encoding="utf-8")
    proc = _run_runtime(runtime, repo)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_adapter_instructs_when_chock_is_not_importable(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = tmp_path / "r"
    (repo / ".chock").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "."], cwd=repo, check=True)
    runtime = _load_runtime(_rendered_runtime(tmp_path))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.setattr(runtime, "_chock_importable", lambda: False)
    import io

    out = io.StringIO()
    code = runtime.main(stdin=io.StringIO(SESSION_START_PAYLOAD), stdout=out, exit=False)
    assert code == 0, "an unarmed clone degrades to advice, never a failed session"
    decision = json.loads(out.getvalue())
    context = decision["hookSpecificOutput"]["additionalContext"]
    assert "chock sync --repo ." in context
    assert "NOT installed" in context


def test_adapter_arms_a_fresh_clone_end_to_end(tmp_path: Path) -> None:
    runtime = _rendered_runtime(tmp_path)
    repo = Path(tempfile.mkdtemp()) / "r"
    repo.mkdir()
    env = {"PYTHONPATH": str(FRAMEWORK_ROOT / "src")}
    subprocess.run(["git", "init", "-q", "."], cwd=repo, check=True)
    subprocess.run(
        [sys.executable, "-m", "chock.cli", "init", "."],
        cwd=repo,
        capture_output=True,
        env={**os.environ, **env},
    )
    pre_commit = repo / ".git" / "hooks" / "pre-commit"
    if pre_commit.exists():
        pre_commit.unlink()

    proc = _run_runtime(runtime, repo, extra_env=env)
    assert proc.returncode == 0
    assert "armed them now" in proc.stdout, proc.stdout + proc.stderr
    assert pre_commit.exists(), "the adapter must reinstall the pre-commit dispatcher"


def test_a_repo_with_no_policies_keeps_the_runtime_its_arm_hook_runs() -> None:
    """The in-agent installer unlinks a runtime nothing wires; the arm hook wires it.

    A fresh `chock init` has the arm hook and no policies. Before this, the pre-tool/stop
    installer ran after the arm hook's, found no fragments, and unlinked `claude_code.py`
    while `.claude/settings.json` still told Claude Code to run it at every session start.
    """
    from chock.hooks.in_agent_install import install_hooks

    repo = _bare_repo()
    assert install_sessionstart_hook(repo) is True
    assert install_hooks(repo, "claude_code") == []
    vendored = repo / ".chock" / "bin" / "claude_code.py"
    assert vendored.is_file(), "the arm hook still points here"
    assert ".chock/bin/claude_code.py" in _entry_command(_settings(repo))


def test_a_repo_with_neither_hook_nor_policy_keeps_no_runtime() -> None:
    """The unlink is still right when nothing at all references the file."""
    from chock.hooks.in_agent_install import install_hooks
    from chock.hooks.runtime_vendor import vendor_runtime

    repo = _bare_repo()
    vendor_runtime(repo, "claude_code")
    assert install_hooks(repo, "claude_code") == []
    assert not (repo / ".chock" / "bin" / "claude_code.py").exists()


def test_the_vendored_runtime_is_written_with_lf_on_every_platform() -> None:
    """The drift check compares this file to the render byte for byte; CRLF is a standing diff."""
    repo = _bare_repo()
    install_sessionstart_hook(repo)
    raw = (repo / ".chock" / "bin" / "claude_code.py").read_bytes()
    assert b"\r" not in raw
    assert raw.decode("utf-8") == runtime_bundle.render("claude_code")

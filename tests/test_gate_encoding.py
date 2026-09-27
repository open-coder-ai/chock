"""The gate must decode git output as UTF-8, never as the machine's locale codec."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import init_repo, stage

from chock.gate import sessionstart, write_gate
from chock.gate.runner import GateContext, run

HOSTILE = {
    "left arrow U+2190": "note = 'value'  # ← chosen default\n",
    "CJK": "# 設定ファイル\n",
    "emoji": "# ✅ verified\n",
}


def _gate(tmp_path: Path, pattern: str) -> Path:
    spec = {
        "kind": "content_regex",
        "on": ["commit"],
        "action": "block",
        "message": "blocked",
        "params": {"scan": "added_lines", "content_pattern": pattern},
    }
    path = tmp_path / "gate.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def test_git_output_is_decoded_as_utf8_not_the_locale_codec(tmp_path: Path) -> None:
    """The direct unit: the accessor must return text, never None."""
    repo = init_repo(tmp_path)
    stage(repo, "notes.md", "# ← arrow\n")
    ctx = GateContext(repo_root=repo)

    lines = ctx.added_lines("notes.md")
    assert lines, "added_lines returned nothing for a staged file"
    assert any("arrow" in line for line in lines)


def test_a_hostile_file_does_not_crash_the_gate(tmp_path: Path) -> None:
    """Whatever the verdict, it must be a verdict -- exit 0 or 1, never a traceback."""
    for label, content in HOSTILE.items():
        case_dir = tmp_path / label.replace(" ", "_")
        case_dir.mkdir()
        repo = init_repo(case_dir)
        stage(repo, "notes.md", content)
        code = run(_gate(repo, "NOTHING_MATCHES_THIS"), "pre-commit", None, repo)
        assert code == 0, f"{label}: gate returned {code} for content it should allow"


def test_a_secret_next_to_hostile_bytes_is_still_caught(tmp_path: Path) -> None:
    """Failing open on undecodable bytes would be the worse bug."""
    repo = init_repo(tmp_path)
    stage(repo, "config.py", "# ← default\nAWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n")  # pragma: allowlist secret

    code = run(_gate(repo, "AKIA[0-9A-Z]{16}"), "pre-commit", None, repo)
    assert code == 1, "the gate missed a secret sitting beside a non-cp1252 character"


# --- the agent-side callers, under a Windows console code page -----------------------------------


RUNNER = Path(__file__).resolve().parents[1] / "src" / "chock" / "gate" / "runner.py"


@pytest.fixture
def cp1252(monkeypatch: pytest.MonkeyPatch) -> None:
    """What subprocess decodes text-mode output with on a Western-European Windows console."""
    monkeypatch.setattr(subprocess, "_text_encoding", lambda: "cp1252")


def test_the_turns_end_sees_a_non_ascii_path(tmp_path: Path, cp1252) -> None:
    """Decoded as cp1252, `café.py` became `cafÃ©.py`, failed to read, and went unjudged."""
    init_repo(tmp_path)
    (tmp_path / "café.py").write_text("x = 1\n", encoding="utf-8")
    assert write_gate.writes_from_worktree(tmp_path) == {"café.py": "x = 1\n"}


def test_the_runners_reason_reaches_the_client_intact(tmp_path: Path, cp1252) -> None:
    gate = tmp_path / ".chock" / "compiled" / "p" / "pre-tool-use" / "gate.json"
    gate.parent.mkdir(parents=True)
    gate.write_text(_gate(tmp_path, "BAD").read_text(encoding="utf-8").replace('"commit"', '"tool_use"'), "utf-8")
    (tmp_path / ".chock" / "bin").mkdir()
    (tmp_path / ".chock" / "bin" / "gate.py").write_text(RUNNER.read_text(encoding="utf-8"), encoding="utf-8")
    event = SimpleNamespace(event="pre_tool", path="café.py", content="BAD\n", raw={})
    verdict = write_gate.evaluate_gate(["--gate", str(gate)], event)
    assert verdict is not None and "café.py" in verdict[1]


def test_the_hooks_path_survives_a_non_ascii_directory(tmp_path: Path, cp1252) -> None:
    (tmp_path / "repo").mkdir()
    repo = init_repo(tmp_path / "repo")
    hooks = tmp_path / "hööks"
    subprocess.run(["git", "config", "core.hooksPath", str(hooks)], cwd=repo, check=True)
    assert sessionstart._hooks_pre_commit(repo) == hooks / "pre-commit"


def test_a_match_cannot_crash_the_runner_on_a_narrow_console(tmp_path: Path) -> None:
    """Printing a non-ASCII match to a cp1252/ascii stderr raised, and exit 1 read as a verdict."""
    repo = init_repo(tmp_path)
    stage(repo, "設定.md", "BAD\n")
    env = {**os.environ, "PYTHONIOENCODING": "ascii", "CHOCK_GATE_LOG": "0"}
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "run", "--gate", str(_gate(tmp_path, "BAD")), "--event", "pre-commit"],
        cwd=repo,
        capture_output=True,
        env=env,
        check=False,
    )
    err = proc.stderr.decode("utf-8")
    assert proc.returncode == 1
    assert "Traceback" not in err
    assert "設定.md" in err

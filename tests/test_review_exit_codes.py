"""Audit-survivor fixes (issue #49): review CLI fail-open exits H2, H4."""

import subprocess
import sys
from pathlib import Path

from chock.review.evidence import run_check


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo_with_commit(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "f.txt").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "f.txt")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "branch", "basepoint")
    (tmp_path / "f.txt").write_text("changed\n", encoding="utf-8")
    _git(tmp_path, "add", "f.txt")
    _git(tmp_path, "commit", "-q", "-m", "change")
    return tmp_path


def test_emit_exits_nonzero_when_a_check_fails(tmp_path):
    """H2: a failing check must fail the emit exit code, not just be printed."""
    repo = _repo_with_commit(tmp_path)
    (repo / ".chock").mkdir()
    config = "chock:" + chr(10) + "  review:" + chr(10) + "    checks:" + chr(10)
    config += '      always-fails: ["python", "-c", "import sys; sys.exit(1)"]' + chr(10)
    (repo / ".chock" / "config.yaml").write_text(config, encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "chock",
            "review",
            "emit",
            "--repo",
            str(repo),
            "--base",
            "basepoint",
            "--by",
            "tester",
            "--checks",
            "always-fails",
        ],
        capture_output=True,
        text=True,
    )
    assert "1 failing" in proc.stdout, proc.stdout + proc.stderr
    assert proc.returncode != 0, "review emit exited 0 with a failing check (H2)"


def test_emit_exits_zero_when_checks_pass(tmp_path):
    repo = _repo_with_commit(tmp_path)
    (repo / ".chock").mkdir()
    config = "chock:" + chr(10) + "  review:" + chr(10) + "    checks:" + chr(10)
    config += '      always-ok: ["python", "-c", "print(1)"]' + chr(10)
    (repo / ".chock" / "config.yaml").write_text(config, encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "chock",
            "review",
            "emit",
            "--repo",
            str(repo),
            "--base",
            "basepoint",
            "--by",
            "tester",
            "--checks",
            "always-ok",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_run_check_survives_systemexit_and_keeps_output(tmp_path):
    """H4: an in-process argparse error (SystemExit 2) must record fail, not crash."""
    status, first = run_check(tmp_path, ["check", "--definitely-not-a-flag"])
    assert status == "fail"
    assert first, "the buffered argparse explanation must be preserved, not discarded"

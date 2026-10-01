"""A throwaway git repository with the installed secret and invisible-Unicode gates, for history scans."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
GATES = ("scan-secrets", "block-invisible-unicode")
SECRET = "AKIA" + "IOSFODNN7EXAMPLE"  # pragma: allowlist secret -- AWS's published example key
BIDI = chr(0x202E)


def git(repo: Path, *args: str, stdin: str | None = None) -> str:
    proc = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args], cwd=repo, input=stdin, capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def make_repo(path: Path, gates: tuple[str, ...] = GATES) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "user.name", "t")
    install_gates(path, gates)
    return path


def install_gates(path: Path, gates: tuple[str, ...] = GATES) -> None:
    for gate in gates:
        dest = path / ".chock" / "compiled" / gate / "git-hook"
        dest.mkdir(parents=True)
        shutil.copy(FRAMEWORK_ROOT / ".chock" / "compiled" / gate / "git-hook" / "gate.json", dest / "gate.json")


def commit(repo: Path, files: dict[str, str | bytes], message: str = "c", removed: tuple[str, ...] = ()) -> str:
    for name, body in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            target.write_bytes(body)
        else:
            target.write_text(body, encoding="utf-8")
        git(repo, "add", "--", name)
    for name in removed:
        git(repo, "rm", "-q", "--", name)
    git(repo, "commit", "-q", "-m", message, "--allow-empty")
    return git(repo, "rev-parse", "HEAD")

"""A throwaway catalog repo for the `chock add --ref` pin tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

ID = "demo-skill"


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def commit(root: Path, body: str) -> str:
    skill = root / "skills" / ID
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(f"---\nname: {ID}\ndescription: demo\n---\n\n{body}\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", body)
    return git(root, "rev-parse", "HEAD")


def make_remote(tmp_path: Path) -> tuple[Path, str, str]:
    """A catalog repo: (path, commit on main, commit on branch `other`)."""
    root = tmp_path / "catalog"
    root.mkdir()
    for args in (
        ("init", "--quiet", "-b", "main"),
        ("config", "user.email", "c@example.invalid"),
        ("config", "user.name", "Catalog"),
        ("config", "uploadpack.allowAnySHA1InWant", "true"),
    ):
        git(root, *args)
    good = commit(root, "good")
    git(root, "checkout", "--quiet", "-b", "other")
    evil = commit(root, "evil")
    git(root, "checkout", "--quiet", "main")
    return root, good, evil

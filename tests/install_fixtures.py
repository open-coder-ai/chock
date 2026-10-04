"""A fixture catalog repo (gate, guard, advisory) and selections pinned to it, for `chock install`."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml
from bundle_fixtures import ADVISORY_ID, GATE_ID, GUARD_ID, make_members

from chock.lock import compute_pack_hash

IDS = (GUARD_ID, GATE_ID, ADVISORY_ID)
VERSION = "0.0.1"


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def make_catalog(tmp_path: Path) -> tuple[Path, str]:
    """A committed catalog in the published layout: (root, commit)."""
    root = tmp_path / "catalog"
    entries = []
    for member in make_members(tmp_path / "authoring", with_advisory=True):
        shutil.copytree(member.policy_dir, root / "base" / member.id)
        entries.append({"id": member.id, "path": f"base/{member.id}", "version": VERSION})
    (root / "registry.yaml").write_text(yaml.safe_dump({"policies": entries}), encoding="utf-8")
    _git(root, "init", "--quiet", "--initial-branch=main")
    _git(root, "add", "-A")
    _git(root, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "--quiet", "-m", "catalog")
    return root, _git(root, "rev-parse", "HEAD")


def side_commit(root: Path) -> str:
    """A commit on a branch other than main, as a fork's commit looks to the source: (sha)."""
    _git(root, "switch", "--quiet", "-c", "side")
    (root / "SIDE.md").write_text("side\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "--quiet", "-m", "side")
    sha = _git(root, "rev-parse", "HEAD")
    _git(root, "switch", "--quiet", "main")
    return sha


def selection(root: Path, ref: str, ids: tuple[str, ...] = IDS, **overrides: Any) -> dict[str, Any]:
    """A valid selection of `ids` pinned to `ref`, with any top-level key overridden."""
    picks = [{"id": i, "version": VERSION, "sha256": compute_pack_hash(root / "base" / i)} for i in ids]
    data = {"schema": 1, "client": "claude-code", "catalog": {"source": str(root), "ref": ref}, "policies": picks}
    return {**data, **overrides}


def write_selection(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def code(data: Any) -> str:
    """The URL-fragment form: compact JSON, base64url, unpadded."""
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

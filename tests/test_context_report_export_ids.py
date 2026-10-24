"""`chock eval export` writes under --out only: a manifest id that is not a policy id is an error, not a path."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from conftest import baseline_policy

from chock.eval import context_report as cr


def _repo_with_id(tmp_path: Path, manifest_id: str) -> Path:
    dest = tmp_path / "repo" / ".agents" / "policies" / "git-safety"
    dest.parent.mkdir(parents=True)
    shutil.copytree(baseline_policy("git-safety"), dest)
    manifest = dest / "manifest.yaml"
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(re.sub(r"(?m)^id:.*$", f"id: '{manifest_id}'", text, count=1), encoding="utf-8")
    return tmp_path / "repo"


@pytest.mark.parametrize("bad", ["../../escaped", "ABSOLUTE", "a/b", "UPPER", "x"])
def test_a_manifest_id_that_is_not_a_policy_id_exports_nothing(tmp_path: Path, bad: str) -> None:
    bad = str(tmp_path / "work" / "escaped") if bad == "ABSOLUTE" else bad
    repo = _repo_with_id(tmp_path, bad)
    out = tmp_path / "work" / "out"

    result = cr.export(repo, out)

    assert result.exported == []
    assert any("not a valid policy id" in e for e in result.errors)
    assert not (tmp_path / "escaped.md").exists()
    assert not (tmp_path / "work" / "escaped.md").exists()
    assert not out.exists() or not any(out.rglob("*.md"))


def test_a_valid_id_still_exports(tmp_path: Path) -> None:
    repo = _repo_with_id(tmp_path, "git-safety")

    result = cr.export(repo, tmp_path / "out")

    assert result.exported == ["git-safety"]

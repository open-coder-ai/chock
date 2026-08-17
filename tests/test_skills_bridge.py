"""Tests for the per-agent skill bridge (.agents/skills/ -> .claude/skills/)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest import mock

import pytest

from chock.scaffold.skills_bridge import update_skill_bridges


def _make_skill(root: Path, skill_id: str) -> Path:
    d = root / ".agents" / "skills" / skill_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"# {skill_id}\n", encoding="utf-8")
    return d


def _bridge_root(tmp_path: Path) -> Path:
    return tmp_path / ".claude" / "skills"


def _fingerprint(root: Path) -> set[tuple[str, int, int]]:
    """Identity of every file in the tree: path, inode, mtime.

    Comparing return values proves nothing about the filesystem -- the first version of
    these tests did exactly that and passed while every skill was being deleted and
    re-copied on each run.
    """
    out = set()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            out.add((str(p.relative_to(root)), st.st_ino, st.st_mtime_ns))
    return out


class TestSymlinkPath:
    def test_creates_link_or_copy(self, tmp_path: Path) -> None:
        """Bridge must produce something at .claude/skills/<id> that exposes SKILL.md."""
        _make_skill(tmp_path, "my-skill")
        result = update_skill_bridges(tmp_path)
        link = _bridge_root(tmp_path) / "my-skill"
        assert "my-skill" in result.get("claude", [])
        assert link.exists()
        assert (link / "SKILL.md").exists()

    def test_symlink_is_relative_when_created(self, tmp_path: Path) -> None:
        """A created symlink must use a relative target so the repo stays portable."""
        _make_skill(tmp_path, "my-skill")
        update_skill_bridges(tmp_path)

        link = _bridge_root(tmp_path) / "my-skill"
        if not link.is_symlink():
            pytest.skip("platform fell back to copy; symlink path not exercised here")
        target = os.readlink(str(link))
        assert not Path(target).is_absolute(), f"Symlink target should be relative, got: {target}"

    def test_idempotent_same_result_twice(self, tmp_path: Path) -> None:
        """Calling bridge twice with unchanged skills must be a no-op on the second call."""
        _make_skill(tmp_path, "my-skill")
        r1 = update_skill_bridges(tmp_path)
        r2 = update_skill_bridges(tmp_path)
        assert r1 == r2
        link = _bridge_root(tmp_path) / "my-skill"
        assert link.exists()

    def test_stale_bridge_removed_when_skill_deleted(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "my-skill")
        update_skill_bridges(tmp_path)
        shutil.rmtree(tmp_path / ".agents" / "skills" / "my-skill")
        update_skill_bridges(tmp_path)
        link = _bridge_root(tmp_path) / "my-skill"
        assert not link.exists()


class TestCopyFallback:
    def test_falls_back_to_copy_on_symlink_failure(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "my-skill")
        with mock.patch("os.symlink", side_effect=OSError("not supported")):
            result = update_skill_bridges(tmp_path)
        assert "my-skill" in result.get("claude", [])
        link = _bridge_root(tmp_path) / "my-skill"
        assert link.exists()
        assert not link.is_symlink()
        assert (link / "SKILL.md").exists()

    def test_copy_is_not_rewritten_when_unchanged(self, tmp_path: Path) -> None:
        """The churn fix: an up-to-date copy must be left alone, not re-copied.

        This is the default path on Windows without Developer Mode, so a rewrite here
        means every refresh rebuilds the whole bridge for no change.
        """
        _make_skill(tmp_path, "my-skill")
        with mock.patch("os.symlink", side_effect=OSError("not supported")):
            update_skill_bridges(tmp_path)
            before = _fingerprint(_bridge_root(tmp_path))
            update_skill_bridges(tmp_path)
            after = _fingerprint(_bridge_root(tmp_path))

        assert before == after, "an unchanged copy was deleted and re-copied"

    def test_stale_copy_is_refreshed_when_source_changes(self, tmp_path: Path) -> None:
        """Skipping matching copies must not leave a stale one behind."""
        skill = _make_skill(tmp_path, "my-skill")
        with mock.patch("os.symlink", side_effect=OSError("not supported")):
            update_skill_bridges(tmp_path)
            (skill / "SKILL.md").write_text("# changed\n", encoding="utf-8")
            update_skill_bridges(tmp_path)

        bridged = _bridge_root(tmp_path) / "my-skill" / "SKILL.md"
        assert bridged.read_text(encoding="utf-8") == "# changed\n"

    def test_new_file_in_source_propagates(self, tmp_path: Path) -> None:
        """A file added to the source skill must appear in the copy."""
        skill = _make_skill(tmp_path, "my-skill")
        with mock.patch("os.symlink", side_effect=OSError("not supported")):
            update_skill_bridges(tmp_path)
            (skill / "reference.md").write_text("extra\n", encoding="utf-8")
            update_skill_bridges(tmp_path)

        assert (_bridge_root(tmp_path) / "my-skill" / "reference.md").exists()

    def test_stale_copy_removed_when_skill_deleted(self, tmp_path: Path) -> None:
        _make_skill(tmp_path, "my-skill")
        with mock.patch("os.symlink", side_effect=OSError("not supported")):
            update_skill_bridges(tmp_path)
        shutil.rmtree(tmp_path / ".agents" / "skills" / "my-skill")
        update_skill_bridges(tmp_path)
        assert not (_bridge_root(tmp_path) / "my-skill").exists()


class TestNoSkillsDir:
    def test_no_skills_dir_returns_empty(self, tmp_path: Path) -> None:
        result = update_skill_bridges(tmp_path)
        assert result == {}


class TestRefreshIntegration:
    def test_refresh_creates_bridge(self, tmp_path: Path) -> None:
        """refresh should invoke the bridge so .claude/skills/ stays in sync."""
        _make_skill(tmp_path, "test-skill")
        (tmp_path / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")

        from chock.index.cli import cmd_refresh

        cmd_refresh(["--repo", str(tmp_path)])
        link = _bridge_root(tmp_path) / "test-skill"
        assert link.exists()
        assert (link / "SKILL.md").exists()

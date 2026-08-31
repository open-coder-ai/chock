"""The skill bridge must never delete an adopter's own .claude/skills/ entries."""

from __future__ import annotations

from pathlib import Path

from chock.scaffold.skills_bridge import _BRIDGE_MARKER, update_skill_bridges


def _chock_skill(repo: Path, name: str) -> None:
    d = repo / ".agents" / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\nbody\n", encoding="utf-8")


def _adopter_skill(repo: Path, name: str) -> Path:
    d = repo / ".claude" / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: mine\n---\nhand-written\n", encoding="utf-8")
    return d


def test_adopter_authored_skill_survives_a_bridge_run(tmp_path: Path) -> None:
    _chock_skill(tmp_path, "policy-init")
    mine = _adopter_skill(tmp_path, "my-team-skill")
    update_skill_bridges(tmp_path)
    assert mine.exists(), "the adopter's own Claude skill was deleted by the bridge"
    assert (mine / "SKILL.md").read_text(encoding="utf-8").endswith("hand-written\n")
    assert (tmp_path / ".claude" / "skills" / "policy-init").exists()


def test_a_removed_chock_skill_bridge_is_still_swept(tmp_path: Path) -> None:
    _chock_skill(tmp_path, "policy-init")
    _chock_skill(tmp_path, "going-away")
    update_skill_bridges(tmp_path)
    assert (tmp_path / ".claude" / "skills" / "going-away").exists()

    import shutil

    shutil.rmtree(tmp_path / ".agents" / "skills" / "going-away")
    update_skill_bridges(tmp_path)
    assert not (tmp_path / ".claude" / "skills" / "going-away").exists(), "stale Chock bridge lingered"
    assert (tmp_path / ".claude" / "skills" / "policy-init").exists()


def test_copy_bridge_is_marked_and_idempotent(tmp_path: Path, monkeypatch) -> None:
    from chock.scaffold import skills_bridge as sb

    def no_symlink(*_a, **_k):
        raise OSError("no symlink privilege")

    monkeypatch.setattr(sb.os, "symlink", no_symlink)
    _chock_skill(tmp_path, "policy-init")
    update_skill_bridges(tmp_path)
    bridge = tmp_path / ".claude" / "skills" / "policy-init"
    assert (bridge / _BRIDGE_MARKER).is_file(), "copy bridge must carry the ownership marker"
    update_skill_bridges(tmp_path)
    assert (bridge / "SKILL.md").exists()
    assert (bridge / _BRIDGE_MARKER).is_file()

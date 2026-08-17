"""Create per-agent symlinks from .agents/skills/ into agent-specific dirs.

Claude Code discovers .claude/skills/<id>/SKILL.md natively. We bridge
.agents/skills/ -> .claude/skills/ so skills are discoverable without
duplicating content. Symlinks are preferred; directory copies are the
automatic fallback on platforms where symlink creation requires elevated
privileges (stock Windows without Developer Mode).
"""

from __future__ import annotations

import filecmp
import os
import shutil
import sys
from pathlib import Path

# Map agent name -> relative path of that agent's skill discovery root.
# Extend here when other agents gain their own discovery path.
AGENT_BRIDGES: dict[str, str] = {
    "claude": ".claude/skills",
}

# Dropped inside every copy-mode bridge Chock creates. `.claude/skills/` is a shared,
# Claude-native location -- an adopter puts their own skills there too -- so the stale
# sweep must delete only the bridges Chock owns. A symlink is owned when it resolves into
# .agents/skills/; a copy is owned when it carries this marker. Anything else is the
# adopter's and is never touched.
_BRIDGE_MARKER = ".chock-bridge"
_BRIDGE_MARKER_BODY = (
    "This directory is a Chock bridge copy of the same-named skill in .agents/skills/.\n"
    "Do not edit it here -- edit the canonical copy; this one is regenerated on every\n"
    "`chock sync`. Safe to delete for the same reason: sync recreates it.\n"
)


def _is_correct_symlink(link: Path, target: Path) -> bool:
    if not link.is_symlink():
        return False
    try:
        return link.resolve() == target.resolve()
    except OSError:
        return False


def _trees_match(src: Path, dst: Path) -> bool:
    """True when dst is already a byte-identical copy of src.

    Without this check the copy fallback rmtree'd and re-copied every skill on every
    refresh. That is the default path on Windows without Developer Mode, so the common
    case was rewriting the whole bridge on each run for no change.
    """
    if not dst.is_dir():
        return False
    src_files = {p.relative_to(src) for p in src.rglob("*") if p.is_file()}
    # The ownership marker lives only in the copy, never in the source, so exclude it from
    # the comparison -- otherwise a marked bridge never matches and is re-copied every run.
    dst_files = {p.relative_to(dst) for p in dst.rglob("*") if p.is_file() and p.name != _BRIDGE_MARKER}
    if src_files != dst_files:
        return False
    return all(filecmp.cmp(src / rel, dst / rel, shallow=False) for rel in src_files)


def _bridge_one(link: Path, target: Path) -> str:
    """Ensure link points at target. Returns 'symlink', 'copy', 'skip', or 'error'."""
    if link.exists() or link.is_symlink():
        if _is_correct_symlink(link, target):
            return "skip"
        # An up-to-date copy is already serving its purpose. Leave it alone rather than
        # replacing it with an identical one; a stale copy still falls through below.
        if link.is_dir() and not link.is_symlink() and _trees_match(target, link):
            _mark_bridge(link)  # back-fill the ownership marker on pre-marker copies
            return "skip"
        if link.is_symlink() or link.is_file():
            link.unlink()
        elif link.is_dir():
            shutil.rmtree(link)

    rel = Path(os.path.relpath(str(target), str(link.parent)))
    try:
        os.symlink(rel, link, target_is_directory=True)
        return "symlink"
    except OSError:
        pass  # elevated privilege not available — fall back to copy

    try:
        shutil.copytree(str(target), str(link))
        _mark_bridge(link)
        return "copy"
    except OSError as exc:
        print(f"[WARN] skills-bridge: could not bridge {target.name}: {exc}", file=sys.stderr)
        return "error"


def _skill_dirs(skills_root: Path) -> list[Path]:
    if not skills_root.exists():
        return []
    return sorted(d for d in skills_root.iterdir() if d.is_dir() and not d.name.startswith("."))


def _mark_bridge(link: Path) -> None:
    """Stamp a copy-mode bridge as Chock-owned. Best effort; a missing marker only means
    a stale copy lingers, never that an adopter's skill is deleted."""
    try:
        marker = link / _BRIDGE_MARKER
        if not marker.exists():
            marker.write_text(_BRIDGE_MARKER_BODY, encoding="utf-8")
    except OSError:
        pass


def _chock_owns(entry: Path, skills_root: Path) -> bool:
    """True only for a bridge Chock created: a symlink into .agents/skills/, or a copy
    carrying the marker. `.claude/skills/` is shared with the adopter's own skills, so
    anything else here is theirs and must never be swept."""
    if entry.is_symlink():
        try:
            return skills_root.resolve() in entry.resolve().parents
        except OSError:
            return False
    if entry.is_dir():
        return (entry / _BRIDGE_MARKER).is_file()
    return False


def _remove_stale(bridge_root: Path, current_ids: set[str], skills_root: Path) -> None:
    for entry in list(bridge_root.iterdir()):
        if entry.name.startswith(".") or entry.name in current_ids:
            continue
        if not _chock_owns(entry, skills_root):
            continue  # adopter-authored .claude/skills/<x>: not ours to delete
        if entry.is_symlink() or entry.is_file():
            entry.unlink()
        elif entry.is_dir():
            shutil.rmtree(str(entry))


def update_skill_bridges(repo_root: Path) -> dict[str, list[str]]:
    """Sync per-agent skill bridge dirs to match .agents/skills/.

    Returns a mapping of agent name -> list of bridged skill ids.
    Idempotent: a second call with unchanged skills touches nothing on disk.
    """
    skills_root = repo_root / ".agents" / "skills"
    if not skills_root.exists():
        return {}

    result: dict[str, list[str]] = {}
    copied: list[str] = []
    for agent, bridge_rel in AGENT_BRIDGES.items():
        bridge_root = repo_root / bridge_rel
        bridge_root.mkdir(parents=True, exist_ok=True)

        skill_dirs = _skill_dirs(skills_root)
        current_ids = {d.name for d in skill_dirs}
        _remove_stale(bridge_root, current_ids, skills_root)

        bridged: list[str] = []
        for skill_dir in skill_dirs:
            mode = _bridge_one(bridge_root / skill_dir.name, skill_dir)
            if mode != "error":
                bridged.append(skill_dir.name)
            if mode == "copy":
                copied.append(skill_dir.name)
        result[agent] = bridged

    # One message per run, not one per skill: six identical warnings every refresh is
    # noise that trains the reader to ignore it.
    if copied:
        print(
            f"[WARN] skills-bridge: symlinks unavailable; copied {len(copied)} skill(s). "
            "Enable Developer Mode on Windows to use symlinks instead.",
            file=sys.stderr,
        )
    return result

"""Create per-agent symlinks from .agents/skills/ into agent-specific dirs."""

from __future__ import annotations

import filecmp
import os
import shutil
import sys
from pathlib import Path

from chock.output import warn
from chock.resources import package_data_dir

AGENT_BRIDGES: dict[str, str] = {
    "claude": ".claude/skills",
}

_BRIDGE_MARKER = ".chock-bridge"
_SCAFFOLD_DATA_DIR = package_data_dir("chock.scaffold", "data")
_BRIDGE_MARKER_BODY = _SCAFFOLD_DATA_DIR.joinpath("bridge_marker.txt").read_text(encoding="utf-8")


def _is_correct_symlink(link: Path, target: Path) -> bool:
    if not link.is_symlink():
        return False
    try:
        return link.resolve() == target.resolve()
    except OSError:
        return False


def _trees_match(src: Path, dst: Path) -> bool:
    """True when dst is already a byte-identical copy of src."""
    if not dst.is_dir():
        return False
    src_files = {p.relative_to(src) for p in src.rglob("*") if p.is_file()}
    dst_files = {p.relative_to(dst) for p in dst.rglob("*") if p.is_file() and p.name != _BRIDGE_MARKER}
    if src_files != dst_files:
        return False
    return all(filecmp.cmp(src / rel, dst / rel, shallow=False) for rel in src_files)


def _bridge_one(link: Path, target: Path) -> str:
    """Ensure link points at target. Returns 'symlink', 'copy', 'skip', or 'error'."""
    if link.exists() or link.is_symlink():
        if _is_correct_symlink(link, target):
            return "skip"
        if link.is_dir() and not link.is_symlink() and _trees_match(target, link):
            _mark_bridge(link)
            return "skip"
        if link.is_symlink() or link.is_file():
            link.unlink()
        elif link.is_dir():
            shutil.rmtree(link)

    rel = Path(os.path.relpath(str(target), str(link.parent)))
    try:
        os.symlink(rel, link, target_is_directory=True)
    except OSError:
        pass
    else:
        return "symlink"

    try:
        shutil.copytree(str(target), str(link))
    except OSError as exc:
        warn(f"skills-bridge: could not bridge {target.name}: {exc}")
        return "error"
    else:
        _mark_bridge(link)
        return "copy"


def _skill_dirs(skills_root: Path) -> list[Path]:
    if not skills_root.exists():
        return []
    return sorted(d for d in skills_root.iterdir() if d.is_dir() and not d.name.startswith("."))


def _mark_bridge(link: Path) -> None:
    """Stamp a copy-mode bridge as Chock-owned. Best effort; a missing marker only means"""
    try:
        marker = link / _BRIDGE_MARKER
        if not marker.exists():
            marker.write_text(_BRIDGE_MARKER_BODY, encoding="utf-8")
    except OSError:
        pass


def _chock_owns(entry: Path, skills_root: Path) -> bool:
    """True only for a bridge Chock created: a symlink into .agents/skills/, or a copy"""
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
            continue
        if entry.is_symlink() or entry.is_file():
            entry.unlink()
        elif entry.is_dir():
            shutil.rmtree(str(entry))


def update_skill_bridges(repo_root: Path) -> dict[str, list[str]]:
    """Sync per-agent skill bridge dirs to match .agents/skills/."""
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

    if copied:
        print(
            f"[WARN] skills-bridge: symlinks unavailable; copied {len(copied)} skill(s). "
            "Enable Developer Mode on Windows to use symlinks instead.",
            file=sys.stderr,
        )
    return result

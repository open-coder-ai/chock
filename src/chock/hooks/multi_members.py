"""The files a folded member is verified by: its policy pack and its compiled tree, each pinned by sha256."""

from __future__ import annotations

from pathlib import Path

from chock.gate.multi import sha256_of
from chock.manifest import CANONICAL_MANIFEST
from chock.policies import discover_policy_dirs

_BYTECODE = ("__pycache__",)
_BYTECODE_SUFFIXES = (".pyc", ".pyo")
_COMPILED = (".chock", "compiled")


def _tree_files(root: Path, base: Path) -> dict[str, str]:
    """{posix path under `base`: sha256} of every file under `root` except bytecode."""
    found = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not (set(path.parts) & set(_BYTECODE) or path.suffix in _BYTECODE_SUFFIXES):
            found[path.relative_to(base).as_posix()] = sha256_of(path)
    return found


def _pack_dir(repo_root: Path, target: Path) -> Path | None:
    """The policy folder a guard script sits in, or the one a compiled artifact was compiled from."""
    for parent in target.parents:
        if (repo_root / parent / CANONICAL_MANIFEST).is_file():
            return repo_root / parent
    parts = target.parts
    if parts[:2] == _COMPILED and len(parts) > len(_COMPILED):
        return next((d for d in discover_policy_dirs(repo_root) if d.name == parts[2]), None)
    return None


def member_files(repo_root: Path, argv: list[str]) -> dict[str, str] | None:
    """The sha256 of every file a single-policy entry for `argv` is verified by: its pack and its compiled tree.

    None when `argv` names no file chock can place, or the file is not among those: such an entry stays as it is.
    """
    root = Path(repo_root)
    target = Path(argv[1]) if len(argv) > 1 else None
    if target is None or target.is_absolute() or ".." in target.parts or not (root / target).is_file():
        return None
    pack = _pack_dir(root, target)
    if pack is None:
        return None
    files = _tree_files(pack, root)
    compiled = root.joinpath(*_COMPILED, pack.name)
    if compiled.is_dir():
        files.update(_tree_files(compiled, root))
    return files if target.as_posix() in files else None

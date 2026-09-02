"""The three packager roles shared by every hook-carrying store: stale, build, diff."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from agentseam import packaging

from chock.emit import write_generated

_DATA = Path(__file__).resolve().parent / "data" / "stores"

FilesFn = Callable[[Path, dict[str, Any], Path], dict[Path, str]]

#: `packaging.supports` is None for codex_cli/cursor's EXECUTABLE part -- agentseam's own
#: evidence standard couldn't establish the location (packaging_limits.py), not that it
#: differs. chock#87 verified `scripts/{name}` for all four stores, so every emitter reads
#: this one constant, borrowed from the two agents where agentseam does record it, instead
#: of repeating the literal.
SCRIPTS_TEMPLATE = packaging.supports("claude_code", packaging.EXECUTABLE)
assert packaging.supports("copilot", packaging.EXECUTABLE) == SCRIPTS_TEMPLATE


def owned_subtrees(store: str) -> tuple[str, ...]:
    """The top-level directories `store`'s package owns, from its store-data file."""
    data = json.loads((_DATA / f"{store}.json").read_text(encoding="utf-8"))
    return tuple(data["owned_subtrees"])


def stale_store_files(
    store: str, files_fn: FilesFn, policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path
) -> list[Path]:
    """Files under this package that the current manifest would no longer produce."""
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return []
    expected = set(files_fn(Path(policy_dir), manifest, Path(repo_root)))
    stale: list[Path] = []
    for sub in owned_subtrees(store):
        for path in sorted((out_dir / sub).rglob("*")) if (out_dir / sub).is_dir() else []:
            if path.is_file() and path.relative_to(out_dir) not in expected:
                stale.append(path)
    return stale


def build_store_plugin(
    store: str, files_fn: FilesFn, policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path
) -> list[Path]:
    """Write `store`'s package for one policy into a distribution directory."""
    written: list[Path] = []
    for rel, content in files_fn(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = Path(out_dir) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_generated(dest, content)
        written.append(dest)

    for stale in stale_store_files(store, files_fn, policy_dir, manifest, repo_root, out_dir):
        stale.unlink()
        parent = stale.parent
        while parent != Path(out_dir) and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    return written


def store_plugin_differences(
    store: str, files_fn: FilesFn, policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path
) -> list[str]:
    """Report where the on-disk package disagrees with what the manifest would produce."""
    policy_id = manifest.get("id") or Path(policy_dir).name
    differences: list[str] = []
    for rel, content in files_fn(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = Path(out_dir) / rel
        if not dest.exists():
            differences.append(f"missing: {policy_id}/{rel.as_posix()}")
        elif dest.read_text(encoding="utf-8") != content:
            differences.append(f"differs: {policy_id}/{rel.as_posix()}")
    for stale in stale_store_files(store, files_fn, policy_dir, manifest, repo_root, out_dir):
        differences.append(f"stale: {policy_id}/{Path(stale).relative_to(Path(out_dir)).as_posix()}")
    return differences

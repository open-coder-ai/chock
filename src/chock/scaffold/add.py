"""`chock add <id>` -- fetch one artifact from a catalog and wire it in."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from chock import yamlio
from chock.config import agents_from_config as _agents_from_config
from chock.lock import LOCAL_SOURCE, compute_pack_hash, is_local_source, read_lock, write_lock
from chock.output import error
from chock.scaffold.pin import PinError, fetch_catalog
from chock.scaffold.recompile import BookkeepingError, recompile


class IntegrityError(RuntimeError):
    """Fetched content did not match the hash the caller required."""


DEFAULT_CATALOG = "https://github.com/open-coder-ai/chock-catalog"

_AREAS = {
    "base": Path(".agents") / "policies",
    "policies": Path(".agents") / "policies",
    "skills": Path(".agents") / "skills",
}


def _reject_unsafe_id(artifact_id: str) -> None:
    """Refuse an artifact id that is anything but a single path component."""
    if artifact_id in ("", ".", "..") or "/" in artifact_id or "\\" in artifact_id or Path(artifact_id).is_absolute():
        msg = f"invalid artifact id {artifact_id!r}: expected a single name, not a path"
        raise ValueError(msg)


def _reject_symlinks(pack_dir: Path, artifact_id: str) -> None:
    """Refuse a pack carrying a symlink: copying it would read a file the catalog never held."""
    links = []
    for parent, dirs, files in os.walk(pack_dir):
        links += [
            Path(parent, n).relative_to(pack_dir).as_posix() for n in dirs + files if Path(parent, n).is_symlink()
        ]
    if links:
        msg = f"{artifact_id}: the catalog pack contains symlink(s): {', '.join(sorted(links))}. Nothing was installed."
        raise IntegrityError(msg)


def _reject_foreign_id(pack_dir: Path, artifact_id: str) -> None:
    """Refuse a pack whose manifest names another id: the folder name is the id everywhere else."""
    manifest = pack_dir / "manifest.yaml"
    if not manifest.is_file():
        return
    try:
        declared = (yamlio.safe_load(manifest.read_text(encoding="utf-8")) or {}).get("id")
    except (yaml.YAMLError, AttributeError) as exc:
        msg = f"{artifact_id}: the catalog pack's manifest.yaml does not parse ({exc}). Nothing was installed."
        raise IntegrityError(msg) from exc
    if declared is not None and str(declared) != artifact_id:
        msg = f"{artifact_id}: the catalog pack's manifest says `id: {declared}`. Nothing was installed."
        raise IntegrityError(msg)


def locate(catalog_root: Path, artifact_id: str) -> tuple[Path, Path]:
    """Find `artifact_id` in the catalog. Returns (source dir, destination area)."""
    _reject_unsafe_id(artifact_id)
    catalog_resolved = catalog_root.resolve()

    registry = catalog_root / "registry.yaml"
    if registry.exists():
        data = yamlio.safe_load(registry.read_text(encoding="utf-8")) or {}
        for entry in data.get("policies", []) or []:
            if entry.get("id") == artifact_id and entry.get("path"):
                candidate = catalog_root / entry["path"]
                if not candidate.resolve().is_relative_to(catalog_resolved):
                    continue
                if (candidate / "manifest.yaml").exists() or (candidate / "SKILL.md").exists():
                    dest = _AREAS["skills"] if entry["path"].startswith("skills/") else _AREAS["base"]
                    return candidate, dest

    for area, dest in _AREAS.items():
        candidate = catalog_root / area / artifact_id
        if (candidate / "manifest.yaml").exists() or (candidate / "SKILL.md").exists():
            return candidate, dest

    searched = ", ".join(f"{a}/" for a in _AREAS)
    msg = f"{artifact_id!r} is not in this catalog (checked registry.yaml and {searched})"
    raise FileNotFoundError(msg)


def verified_pack(catalog: Path, artifact_id: str, verify_sha: str | None) -> tuple[Path, Path, str]:
    """Locate one artifact in a fetched catalog, refuse an unsafe pack, check its hash: (source, area, sha256)."""
    src, area = locate(catalog, artifact_id)
    _reject_symlinks(src, artifact_id)
    _reject_foreign_id(src, artifact_id)
    digest = compute_pack_hash(src)
    if verify_sha and digest != verify_sha:
        msg = f"{artifact_id}: expected sha256 {verify_sha}, got {digest}. Nothing was installed."
        raise IntegrityError(msg)
    return src, area, digest


@dataclass
class Added:
    """Where an artifact landed, and the provenance worth recording about it."""

    path: Path
    sha256: str
    commit: str | None = None


def add(
    repo_root: Path,
    artifact_id: str,
    source: str,
    ref: str | None,
    *,
    force: bool,
    verify_sha: str | None = None,
) -> Added:
    """Copy one artifact into the repo. Returns where it landed and what it hashed to."""
    with tempfile.TemporaryDirectory(prefix="chock-add-") as tmp:
        catalog, commit = fetch_catalog(source, ref, Path(tmp) / "catalog")
        src, area, digest = verified_pack(catalog, artifact_id, verify_sha)

        dest = repo_root / area / artifact_id
        if dest.exists() and not force:
            msg = f"{area.as_posix()}/{artifact_id} already exists; use --force to replace it"
            raise FileExistsError(msg)
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest)
        return Added(path=dest, sha256=digest, commit=commit)


def record_provenance(repo_root: Path, artifact_id: str, source: str, ref: str | None, added: Added) -> None:
    """Write where a pack came from into chock.lock."""
    lock = read_lock(repo_root)
    for entry in lock.get("packs", []):
        if entry.get("id") != artifact_id:
            continue
        if is_local_source(source, repo_root):
            entry["source"] = LOCAL_SOURCE
            entry.pop("source_commit", None)
            entry.pop("source_ref", None)
        else:
            entry["source"] = source
            entry["source_commit"] = added.commit
            if ref:
                entry["source_ref"] = ref
        write_lock(lock, repo_root)
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chock add", description="Install a policy or skill from a catalog and compile it"
    )
    parser.add_argument("artifact_id", help="Policy or skill id, e.g. protect-main-branch")
    parser.add_argument("--repo", default=".", help="Target repo root")
    parser.add_argument("--from", dest="source", default=DEFAULT_CATALOG, help="Catalog URL or local path")
    parser.add_argument("--ref", default=None, help="Full 40-hex commit SHA (recommended), or a branch/tag (mutable)")
    parser.add_argument("--force", action="store_true", help="Replace an artifact that is already installed")
    parser.add_argument("--skip-compile", action="store_true", help="Copy only; do not compile or install hooks")
    parser.add_argument(
        "--verify-sha",
        default=None,
        metavar="SHA256",
        help="Refuse to install unless the fetched artifact hashes to this value",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    try:
        added = add(repo_root, args.artifact_id, args.source, args.ref, force=args.force, verify_sha=args.verify_sha)
    except PinError as exc:
        print(exc, file=sys.stderr)
        return 2
    except (RuntimeError, ValueError, FileNotFoundError, FileExistsError) as exc:
        print(f"chock add: {exc}", file=sys.stderr)
        return 1

    rel = added.path.relative_to(repo_root).as_posix()
    print(f"Added {args.artifact_id} to {rel}")

    if added.commit:
        print(f"  from {args.source} at {added.commit}")
    print(f"  sha256 {added.sha256}")
    if not args.ref and added.commit:
        print(f"  (unpinned: this was the default branch. Pin with --ref, or --verify-sha {added.sha256})")

    if args.skip_compile:
        print("Run `chock sync --repo .` to compile it.")
        return 0

    try:
        agents = _agents_from_config(repo_root)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        recompile(repo_root, agents, skip_hooks=True)
    except BookkeepingError as exc:
        error(str(exc))
        return 1
    record_provenance(repo_root, args.artifact_id, args.source, args.ref, added)
    print("Compiled. Run `chock sync --repo .` to activate commit-time enforcement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

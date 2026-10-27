"""chock.lock management and drift verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from chock.policies import discover_policy_dirs
from chock.scaffold.pin import is_remote_source
from chock.vendored import vendored_differences

LOCKFILE_NAME = "chock.lock"
LOCKFILE_VERSION = "2"
ENGINE_CONSTRAINT = ">=0.1,<0.2"
POLICIES_REL = Path(".agents") / "policies"
LOCAL_SOURCE = "local"
_PROVENANCE_KEYS = ("source", "source_commit", "source_ref")


class LockError(RuntimeError):
    """chock.lock exists but cannot be read as a lockfile."""


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


#: What Python writes beside a module it imports. A script gate runs its implementation from the
#: pack directory, so the first gate run leaves bytecode there -- per interpreter version, and more
#: of it as more rules are imported. Hashing it made the lockfile depend on which gates had run on
#: which Python, and `chock check` report a pack nobody edited as changed.
_BYTECODE_DIR = "__pycache__"
_BYTECODE_SUFFIXES = (".pyc", ".pyo")


def _is_bytecode(path: Path) -> bool:
    return _BYTECODE_DIR in path.parts or path.suffix in _BYTECODE_SUFFIXES


def _is_pack_content(path: Path) -> bool:
    return path.is_file() and not _is_bytecode(path)


def pack_bytecode(pack_dir: Path) -> list[str]:
    """Posix-relative names of the build artifacts a pack ships: `__pycache__` entries and `.pyc`/`.pyo` files."""
    found = (p.relative_to(pack_dir).as_posix() for p in pack_dir.rglob("*") if p.is_file() and _is_bytecode(p))
    return sorted(found)


def _pack_files(pack_dir: Path) -> list[tuple[str, Path]]:
    """(posix-relative name, path) in code-point order of the name: the same order on every platform.

    Sorting `Path` objects compares case-insensitively on Windows, so a pack holding `LICENSE` beside
    `hooks/` hashed differently there from the hash a Linux checkout recorded.
    """
    named = ((p.relative_to(pack_dir).as_posix(), p) for p in pack_dir.rglob("*") if _is_pack_content(p))
    return sorted(named, key=lambda item: item[0])


#: v2 domain separator: the first bytes hashed, so a pack hash is never a sha256 of anything else chock hashes.
PACK_HASH_V2_DOMAIN = b"chock-pack-hash-v2\n"


def compute_pack_hash(pack_dir: Path) -> str:
    """Pack hash v2: lowercase hex sha256 of a framed byte stream; every writer writes this.

    Files are every regular file under `pack_dir` except bytecode (`__pycache__` anywhere in the path,
    `.pyc`, `.pyo`), named by their posix path relative to `pack_dir`, sorted by the UTF-8 bytes of the name
    (the same as code-point order). Content is the raw bytes, no newline conversion. The stream is

        "chock-pack-hash-v2\n"                                                  (19 ASCII bytes)
        then per file:  u64be(len(name_utf8)) name_utf8 u64be(len(content)) content

    where u64be is an 8-byte big-endian unsigned integer. An empty pack hashes the domain bytes alone.
    """
    return _hash_v2(_read_pack(pack_dir))


def _read_pack(pack_dir: Path) -> list[tuple[bytes, bytes]]:
    """(utf-8 name, content) per pack file, in hash order."""
    return [(rel.encode("utf-8"), f.read_bytes()) for rel, f in _pack_files(pack_dir)]


def _hash_v2(files: list[tuple[bytes, bytes]]) -> str:
    h = hashlib.sha256(PACK_HASH_V2_DOMAIN)
    for name, content in files:
        h.update(len(name).to_bytes(8, "big") + name + len(content).to_bytes(8, "big"))
        h.update(content)
    return h.hexdigest()


def _hash_v1(files: list[tuple[bytes, bytes]]) -> str:
    """Pack hash v1 (`name NUL content NUL` per file): kept only to recognise old hashes, never written."""
    h = hashlib.sha256()
    for name, content in files:
        h.update(name + b"\0" + content + b"\0")
    return h.hexdigest()


def pack_hash_matches(pack_dir: Path, expected: object) -> bool:
    """True when `pack_dir` hashes to `expected` under v2, or under v1 while no file holds a NUL byte.

    With a NUL byte in a file v1's framing is ambiguous (two file sets can share a hash), so a v1 hash is
    refused there. v1 is accepted for all of 1.x and removed in 2.0. Every comparison of a stored or given pack hash goes through this function.
    """
    if not isinstance(expected, str):
        return False
    files = _read_pack(pack_dir)
    if _hash_v2(files) == expected:
        return True
    return all(b"\0" not in content for _name, content in files) and _hash_v1(files) == expected


def read_lock(repo_root: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root or Path.cwd().resolve()
    path = repo_root / LOCKFILE_NAME
    if not path.exists():
        return {"lockfile_version": LOCKFILE_VERSION, "engine": ENGINE_CONSTRAINT, "packs": []}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        msg = f"{LOCKFILE_NAME} is not valid JSON ({exc}); restore it from git or run `chock sync` to rewrite it"
        raise LockError(msg) from exc
    if not isinstance(loaded, dict) or not isinstance(loaded.get("packs", []), list):
        msg = f"{LOCKFILE_NAME} is not a lockfile (expected an object with a `packs` list)"
        raise LockError(msg)
    return loaded


def write_lock(data: dict[str, Any], repo_root: Path | None = None) -> None:
    repo_root = repo_root or Path.cwd().resolve()
    path = repo_root / LOCKFILE_NAME
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")


def compute_artifacts_hash(repo_root: Path, policy_id: str) -> str | None:
    """Hash the compiled tree a pack produced, or None when it has not been compiled."""
    compiled_dir = repo_root / ".chock" / "compiled" / policy_id
    if not compiled_dir.is_dir():
        return None
    return compute_pack_hash(compiled_dir)


def _pack_rel(entry: dict[str, Any]) -> Path:
    """Where a locked pack lives: a nested pack records its path, a top-level one is its id."""
    return Path(entry["path"]) if entry.get("path") else POLICIES_REL / entry["id"]


def is_local_source(source: object, repo_root: Path) -> bool:
    """True for every spelling of "this repo itself": `local`, `.`, or a path that resolves to the repo root."""
    if not isinstance(source, str) or not source:
        return False
    if source in {LOCAL_SOURCE, "."}:
        return True
    if is_remote_source(source):
        return False
    try:
        return Path(source).expanduser().resolve() == repo_root.resolve()
    except (OSError, RuntimeError):
        return False


def _prior_provenance(repo_root: Path) -> dict[str, dict[str, Any]]:
    """Catalog provenance recorded by `chock add`, by pack path; local spellings are dropped (canonical form)."""
    try:
        packs = read_lock(repo_root).get("packs", [])
    except LockError:
        return {}
    found: dict[str, dict[str, Any]] = {}
    for entry in packs:
        if not isinstance(entry, dict) or "id" not in entry or is_local_source(entry.get("source"), repo_root):
            continue
        found[_pack_rel(entry).as_posix()] = entry
    return found


def build_lock(repo_root: Path) -> dict[str, Any]:
    """Build a lockfile from the policies installed in a repo: every pack `sync` compiles.

    A local pack is `source: local` with no `source_commit`. Catalog provenance survives while the pack
    still hashes to what was fetched; an edited pack is local again.
    """
    prior = _prior_provenance(repo_root)
    lock: dict[str, Any] = {
        "lockfile_version": LOCKFILE_VERSION,
        "engine": ENGINE_CONSTRAINT,
        "packs": [],
    }
    for pack_dir in discover_policy_dirs(repo_root):
        entry: dict[str, Any] = {
            "id": pack_dir.name,
            "version": "0.0.1",
            "managed": False,
            "sha256": compute_pack_hash(pack_dir),
            "source": LOCAL_SOURCE,
        }
        if pack_dir.parent != repo_root / POLICIES_REL:
            entry["path"] = pack_dir.relative_to(repo_root).as_posix()
        fetched = prior.get(pack_dir.relative_to(repo_root).as_posix())
        if fetched and pack_hash_matches(pack_dir, fetched.get("sha256")):
            entry.update({k: fetched[k] for k in _PROVENANCE_KEYS if k in fetched})
        artifacts = compute_artifacts_hash(repo_root, pack_dir.name)
        if artifacts is not None:
            entry["artifacts_sha256"] = artifacts
        lock["packs"].append(entry)

    return lock


def verify_lock(repo_root: Path | None = None) -> tuple[bool, list[str]]:
    """Recompute pack and compiled-artifact hashes and report drift."""
    repo_root = repo_root or Path.cwd().resolve()
    try:
        lock = read_lock(repo_root)
    except LockError as exc:
        return False, [str(exc)]
    failures: list[str] = []

    failures += [
        f"vendored runtime modified ({d}) -- this is what executes gates" for d in vendored_differences(repo_root)
    ]

    locked = {_pack_rel(entry).as_posix() for entry in lock.get("packs", [])}
    for pack_dir in discover_policy_dirs(repo_root):
        rel = pack_dir.relative_to(repo_root).as_posix()
        if rel not in locked:
            failures.append(f"{pack_dir.name}: installed at {rel} but not in {LOCKFILE_NAME} (run `chock sync`)")

    for entry in lock.get("packs", []):
        pack_dir = repo_root / _pack_rel(entry)
        if not pack_dir.exists():
            failures.append(f"{entry['id']}: pack directory missing")
            continue
        failures += [
            f"{entry['id']}: ships build artifact {name} (bytecode is never catalog content; delete it)"
            for name in pack_bytecode(pack_dir)
        ]
        if not pack_hash_matches(pack_dir, entry.get("sha256")):
            failures.append(
                f"{entry['id']}: hash mismatch (expected {entry.get('sha256')}, got {compute_pack_hash(pack_dir)})"
            )

        expected_artifacts = entry.get("artifacts_sha256")
        if expected_artifacts is None:
            continue
        compiled_dir = repo_root / ".chock" / "compiled" / entry["id"]
        if not compiled_dir.is_dir():
            failures.append(f"{entry['id']}: compiled artifacts missing (nothing is enforcing this policy)")
        elif not pack_hash_matches(compiled_dir, expected_artifacts):
            failures.append(
                f"{entry['id']}: compiled artifact hash mismatch "
                f"(expected {expected_artifacts}, got {compute_artifacts_hash(repo_root, entry['id'])}) -- "
                "the artifact that enforces is not the one that was locked"
            )

    return (not failures, failures)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    valid_commands = {"init", "verify"}
    if not argv or argv[0] not in valid_commands:
        argv = ["verify", *argv]

    root_parser = argparse.ArgumentParser(add_help=False)
    root_parser.add_argument("--root", "--repo", default=".", dest="root", help="Repo root")

    parser = argparse.ArgumentParser(description="Manage chock.lock")
    sub = parser.add_subparsers(dest="command", required=False)
    sub.add_parser("init", parents=[root_parser], help="Write chock.lock from installed packs")
    sub.add_parser("verify", parents=[root_parser], help="Verify installed packs match the lockfile")
    args = parser.parse_args(argv)

    repo_root = Path(args.root).resolve()
    if args.command == "init":
        lock = build_lock(repo_root)
        write_lock(lock, repo_root)
        print(f"Wrote {LOCKFILE_NAME} with {len(lock['packs'])} pack(s)")
        return 0
    if args.command == "verify":
        ok, failures = verify_lock(repo_root)
        if ok:
            print("verify: all packs match lockfile")
            return 0
        for f in failures:
            print(f"verify FAIL: {f}", file=sys.stderr)
        return 1
    return 2

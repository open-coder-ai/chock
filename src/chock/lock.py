"""chock.lock management and drift verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from chock.manifest import resolve_manifest_path

LOCKFILE_NAME = "chock.lock"
LOCKFILE_VERSION = "1"
ENGINE_CONSTRAINT = ">=0.1,<0.2"


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def compute_pack_hash(pack_dir: Path) -> str:
    """Return a single sha256 for all files in a pack directory."""
    files = sorted(p for p in pack_dir.rglob("*") if p.is_file())
    h = hashlib.sha256()
    for f in files:
        rel = f.relative_to(pack_dir).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def read_lock(repo_root: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root or Path.cwd().resolve()
    path = repo_root / LOCKFILE_NAME
    if not path.exists():
        return {"lockfile_version": LOCKFILE_VERSION, "engine": ENGINE_CONSTRAINT, "packs": []}
    return json.loads(path.read_text(encoding="utf-8"))


def write_lock(data: dict[str, Any], repo_root: Path | None = None) -> None:
    repo_root = repo_root or Path.cwd().resolve()
    path = repo_root / LOCKFILE_NAME
    # newline="\n", not bare write_text: on Windows the latter emits CRLF, so every sync
    # rewrote chock.lock with the other platform's line endings -- a no-op recompile showed
    # the lockfile as modified, the git-status noise emit.write_generated exists to prevent.
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")


def compute_artifacts_hash(repo_root: Path, policy_id: str) -> str | None:
    """Hash the compiled tree a pack produced, or None when it has not been compiled.

    The pack hash covers `.agents/policies/<id>` -- the source. What actually enforces is
    `.chock/compiled/<id>`, and nothing hashed it: deleting or weakening a compiled
    gate left `verify` printing "all packs match lockfile" while enforcement was off. A
    lockfile that attests the wrong artifact is worse than none, because it is quoted as
    evidence.
    """
    compiled_dir = repo_root / ".chock" / "compiled" / policy_id
    if not compiled_dir.is_dir():
        return None
    return compute_pack_hash(compiled_dir)


def build_lock(repo_root: Path, source_root: Path | None = None) -> dict[str, Any]:
    """Build a lockfile from the policies installed in a repo.

    Every pack is `managed: false` / `source: local`. The framework ships no policies, so
    there is no framework-owned tree to distinguish from the adopter's -- content is
    installed, and once installed it is theirs.
    """
    lock: dict[str, Any] = {
        "lockfile_version": LOCKFILE_VERSION,
        "engine": ENGINE_CONSTRAINT,
        "packs": [],
    }
    policies_dir = repo_root / ".agents" / "policies"
    if policies_dir.exists():
        for pack_dir in sorted(policies_dir.iterdir()):
            if not pack_dir.is_dir():
                continue
            manifest = resolve_manifest_path(pack_dir)
            if manifest is None:
                continue
            entry: dict[str, Any] = {
                "id": pack_dir.name,
                "version": "0.0.1",
                "managed": False,
                "sha256": compute_pack_hash(pack_dir),
                "source": "local",
            }
            artifacts = compute_artifacts_hash(repo_root, pack_dir.name)
            if artifacts is not None:
                entry["artifacts_sha256"] = artifacts
            lock["packs"].append(entry)

    return lock


def verify_lock(repo_root: Path | None = None) -> tuple[bool, list[str]]:
    """Recompute pack and compiled-artifact hashes and report drift."""
    repo_root = repo_root or Path.cwd().resolve()
    lock = read_lock(repo_root)
    failures: list[str] = []

    # The vendored runtimes are not hashed per pack -- they are shared by every policy in the
    # repo -- but they are what executes, so `verify` has to judge them. Skipping them left
    # the attestation command reporting "all packs match" against a runner whose `run()` had
    # been replaced with `return 0`, which is the one bypass that disables every gate at once.
    # Imported here rather than at module scope: `lock` is imported by callers that only
    # need the hashing helpers, and the drift check pulls in importlib.resources.
    from chock.vendored import vendored_differences

    failures += [
        f"vendored runtime modified ({d}) -- this is what executes gates" for d in vendored_differences(repo_root)
    ]

    for entry in lock.get("packs", []):
        pack_dir = repo_root / ".agents" / "policies" / entry["id"]
        if not pack_dir.exists():
            failures.append(f"{entry['id']}: pack directory missing")
            continue
        actual = compute_pack_hash(pack_dir)
        if actual != entry.get("sha256"):
            failures.append(f"{entry['id']}: hash mismatch (expected {entry.get('sha256')}, got {actual})")

        # Optional on read, so a lockfile written before this field existed reports as
        # unpinned rather than as a false mismatch. It is written on the next `verify init`
        # or `recompile`.
        expected_artifacts = entry.get("artifacts_sha256")
        if expected_artifacts is None:
            continue
        actual_artifacts = compute_artifacts_hash(repo_root, entry["id"])
        if actual_artifacts is None:
            failures.append(f"{entry['id']}: compiled artifacts missing (nothing is enforcing this policy)")
        elif actual_artifacts != expected_artifacts:
            failures.append(
                f"{entry['id']}: compiled artifact hash mismatch "
                f"(expected {expected_artifacts}, got {actual_artifacts}) -- "
                "the artifact that enforces is not the one that was locked"
            )

    return (not failures, failures)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    valid_commands = {"init", "verify"}
    if not argv or argv[0] not in valid_commands:
        argv = ["verify"] + argv

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

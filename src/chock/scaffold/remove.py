"""Remove an installed policy: the missing symmetry for `add`.

Without this, `add` was a one-way door -- an adopter could only `disable` a policy,
leaving its folder, compiled artifacts, and lockfile entry behind forever.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from chock.compile.compiler import _load_manifest
from chock.policies import discover_policy_dirs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chock remove", description="Remove an installed policy and resync")
    parser.add_argument("policy_id", help="Policy identifier to remove")
    parser.add_argument("--repo", default=".", help="Repo root")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    target: Path | None = None
    manifest: dict = {}
    for pack_dir in discover_policy_dirs(repo_root):
        manifest = _load_manifest(pack_dir)
        if manifest.get("id") == args.policy_id or pack_dir.name == args.policy_id:
            target = pack_dir
            break

    if target is None:
        print(f"Unknown policy: {args.policy_id}", file=sys.stderr)
        return 2
    if manifest.get("mandatory"):
        print(f"Cannot remove mandatory policy: {args.policy_id}", file=sys.stderr)
        return 2

    shutil.rmtree(target)
    print(f"Removed {target.relative_to(repo_root).as_posix()}")

    # Resync so the compiled tree, hooks, index, registry, and lockfile all stop
    # describing a policy that no longer exists.
    from chock.lifecycle import sync_main

    return sync_main(["--repo", str(repo_root)])


if __name__ == "__main__":
    raise SystemExit(main())

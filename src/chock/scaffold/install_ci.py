#!/usr/bin/env python3
"""Install a GitHub Actions workflow that runs the compiled ci-gate surface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chock.emit import write_generated
from chock.resources import package_data_dir

_DATA_DIR = package_data_dir("chock.scaffold", "data")
WORKFLOW_TEMPLATE = _DATA_DIR.joinpath("ci_workflow.yml").read_text(encoding="utf-8")
MARKER = WORKFLOW_TEMPLATE.splitlines()[0]


DEFAULT_PATH = ".github/workflows/chock.yml"


def ci_workflow_installed(repo_root: Path, path: str = DEFAULT_PATH) -> bool:
    """True when this repo's copy of the workflow at `path` is ours, not merely present."""
    dest = Path(repo_root) / path
    if not dest.exists():
        return False
    try:
        return MARKER in dest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the Chock CI gate workflow")
    parser.add_argument("repo_root", nargs="?", default=".", help="Repository root (default: .)")
    parser.add_argument(
        "--path", default=".github/workflows/chock.yml", help="Workflow file to write, relative to repo_root"
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    dest = repo_root / args.path

    if dest.exists():
        existing = dest.read_text(encoding="utf-8", errors="replace")
        if MARKER not in existing:
            print(
                f"[ERROR] {dest} already exists and was not written by chock. "
                "Remove it or pass --path to choose a different file.",
                file=sys.stderr,
            )
            return 1
        if existing == WORKFLOW_TEMPLATE:
            print(f"{dest} is already up to date")
            return 0

    dest.parent.mkdir(parents=True, exist_ok=True)
    write_generated(dest, WORKFLOW_TEMPLATE)
    print(f"Installed CI workflow at {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

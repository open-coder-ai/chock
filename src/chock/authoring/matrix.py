#!/usr/bin/env python3
"""Verify that every spec invariant ID appears in the enforcement matrix.

Scans spec/ for invariant IDs (e.g. SEC-1, DET-2) and ensures each one has a
matching row in spec/enforcement-matrix.md. Fails if any spec invariant is
missing from the matrix or if a matrix row lacks a Check column.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path.cwd()  # repo-root tool: operates on the current working directory
SPEC_DIR = ROOT / "spec"
MATRIX_FILE = SPEC_DIR / "enforcement-matrix.md"

INVARIANT_RE = re.compile(r"\*\*([A-Z]{2,4}-\d+)\*\*")
MATRIX_ID_RE = re.compile(r"^\|\s*([A-Z]{2,4}-\d+)\s*\|")


def collect_spec_invariant_ids() -> set[str]:
    ids: set[str] = set()
    for path in SPEC_DIR.rglob("*.md"):
        if path == MATRIX_FILE:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for match in INVARIANT_RE.finditer(text):
            ids.add(match.group(1))
    return ids


def collect_matrix_ids_and_rows() -> tuple[set[str], list[str]]:
    ids: set[str] = set()
    rows_without_check: list[str] = []
    text = MATRIX_FILE.read_text(encoding="utf-8")
    for line in text.splitlines():
        match = MATRIX_ID_RE.match(line)
        if not match:
            continue
        inv_id = match.group(1)
        ids.add(inv_id)
        # A valid row must have at least 5 pipe-separated columns and a non-empty Check column.
        parts = [p.strip() for p in line.split("|")]
        # parts[0] is empty before the first |, parts[1] is ID, parts[3] is Check, etc.
        if len(parts) < 5 or not parts[3] or parts[3].lower() == "check":
            rows_without_check.append(line.strip())
    return ids, rows_without_check


USAGE = """usage: chock check --only matrix

Verify that every spec invariant ID appears in spec/enforcement-matrix.md, and that no matrix
row is missing its Check column. Takes no options; reads spec/ from the current directory.

For work on Chock itself. Anywhere without spec/enforcement-matrix.md it exits non-zero.
"""


def main(argv=None) -> int:
    # The only command taking no arguments, so it parsed none -- and `check-matrix --help`
    # therefore ran the check and failed with "enforcement matrix not found", which reads like
    # a broken install rather than a misunderstanding about flags. Every other command answers
    # --help; matching them is cheaper than the support question.
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE.strip())
        return 0

    if not MATRIX_FILE.exists():
        print(f"ERROR: enforcement matrix not found: {MATRIX_FILE}", file=sys.stderr)
        print("       check-matrix is for work on Chock itself, not adopter repos.", file=sys.stderr)
        return 1

    spec_ids = collect_spec_invariant_ids()
    matrix_ids, rows_without_check = collect_matrix_ids_and_rows()

    missing = sorted(spec_ids - matrix_ids)
    if missing:
        print("ERROR: spec invariant IDs missing from enforcement matrix:", file=sys.stderr)
        for inv_id in missing:
            print(f"  - {inv_id}", file=sys.stderr)
        return 1

    if rows_without_check:
        print("ERROR: matrix rows missing a Check column:", file=sys.stderr)
        for row in rows_without_check:
            print(f"  - {row}", file=sys.stderr)
        return 1

    print(f"OK: all {len(spec_ids)} spec invariant IDs are present in the enforcement matrix.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

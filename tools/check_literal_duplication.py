#!/usr/bin/env python3
"""Sonar S1192-style check: string literals repeated 3+ times are a maintenance bug.

Flags any non-docstring string constant, >= MIN_LITERAL_LEN chars, that appears
>= MIN_OCCURRENCES times across the scanned Python files, outside data/, templates/
and tests/ directories (those are expected to hold or exercise repeated text) --
unless the literal is listed in literal_duplication_allowlist.json with a reason.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import defaultdict
from pathlib import Path

MIN_LITERAL_LEN = 20
MIN_OCCURRENCES = 3

#: Path segments whose contents are expected to hold or exercise repeated text.
_EXCLUDED_PATH_PARTS = {"data", "templates", "tests"}
#: Vendored/bundled output, not source this check should police (see pyproject.toml
#: [tool.ruff] extend-exclude for the matching rationale).
_EXCLUDED_PATH_PREFIXES = (".chock/bin",)

ALLOWLIST_PATH = Path(__file__).with_name("literal_duplication_allowlist.json")


class AllowlistEntryMissingReasonError(ValueError):
    """An allowlist entry has no (or a blank) reason explaining the duplication."""

    def __init__(self, literal: str) -> None:
        super().__init__(f"literal_duplication_allowlist.json entry has no reason: {literal!r}")


def _docstring_node_ids(tree: ast.Module) -> set[int]:
    """id() of every Constant node that is a module/class/function docstring."""
    ids: set[int] = set()
    scopes: list[ast.AST] = [tree]
    scopes.extend(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef))
    for node in scopes:
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            ids.add(id(first.value))
    return ids


def _literals_in_file(path: Path) -> list[str]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return []
    skip_ids = _docstring_node_ids(tree)
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and len(node.value) >= MIN_LITERAL_LEN
        and id(node) not in skip_ids
    ]


def _is_excluded(rel_path: Path) -> bool:
    posix = rel_path.as_posix()
    if any(posix.startswith(prefix) for prefix in _EXCLUDED_PATH_PREFIXES):
        return True
    return any(part in _EXCLUDED_PATH_PARTS for part in rel_path.parts[:-1])


def scan(root: Path) -> dict[str, list[Path]]:
    """Map each qualifying literal to every file it occurs in (repeats included)."""
    occurrences: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(root.rglob("*.py")):
        if _is_excluded(path.relative_to(root)):
            continue
        for literal in _literals_in_file(path):
            occurrences[literal].append(path)
    return occurrences


def load_allowlist() -> dict[str, str]:
    """literal -> reason. Raises if any entry lacks a non-empty reason."""
    if not ALLOWLIST_PATH.exists():
        return {}
    raw = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    for literal, reason in raw.items():
        if not isinstance(reason, str) or not reason.strip():
            raise AllowlistEntryMissingReasonError(literal)
    return raw


def find_violations(root: Path) -> dict[str, list[Path]]:
    """Qualifying literals repeated >= MIN_OCCURRENCES times and not allowlisted."""
    allowlist = load_allowlist()
    occurrences = scan(root)
    return {
        literal: files
        for literal, files in occurrences.items()
        if len(files) >= MIN_OCCURRENCES and literal not in allowlist
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default="src", help="directory to scan (default: src)")
    args = parser.parse_args(argv)
    violations = find_violations(Path(args.root))
    if not violations:
        print("No repeated literals found.")
        return 0
    for literal, files in sorted(violations.items(), key=lambda kv: -len(kv[1])):
        print(f"{len(files)}x {literal!r}", file=sys.stderr)
        for f in files:
            print(f"    {f}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

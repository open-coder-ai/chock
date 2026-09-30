#!/usr/bin/env python3
"""Refuse a commit whose actual message carries a process-leak marker; git hands the message file as argv[1]."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCISSORS = "# ------------------------ >8 ------------------------"
UNCHECKED = "protect-commit-privacy-commit-msg: {why}; commit message not checked"


def load_guard():
    """The command guard, whose MARKERS this check applies to the message; chock_shellparse sits beside it."""
    sys.path.insert(0, str(HERE))
    try:
        return importlib.import_module("protect-commit-privacy")
    finally:
        sys.path.remove(str(HERE))


def message_body(text: str) -> str:
    """The message git would keep: comment lines dropped, and a `commit --verbose` diff below the scissors line cut."""
    kept = []
    for line in text.splitlines():
        if line.startswith(SCISSORS):
            break
        if not line.startswith("#"):
            kept.append(line)
    return "\n".join(kept)


def marker_in(text: str, markers: tuple[str, ...]) -> str | None:
    """The first marker the message carries, matched case-insensitively as the guard does, or None."""
    lowered = message_body(text).lower()
    return next((marker for marker in markers if marker in lowered), None)


def run(argv: list[str]) -> int:
    """Exit 1 refuses the commit, 2 reports a fault in this check (the commit is refused too), 0 lets it go."""
    if len(argv) != 1:
        print(UNCHECKED.format(why="git passes the message file as the one argument"), file=sys.stderr)
        return 2
    try:
        text = Path(argv[0]).read_text(encoding="utf-8", errors="replace")
        marker = marker_in(text, load_guard().MARKERS)
    except Exception as exc:  # noqa: BLE001 -- say what failed instead of a bare traceback
        print(UNCHECKED.format(why=f"internal error ({type(exc).__name__})"), file=sys.stderr)
        return 2
    if marker is None:
        return 0
    print(
        f"BLOCKED: commit message narrates the development process ('{marker}'). Describe the change itself; keep "
        "conversations, plans, session links and decision trails out of published history -- on a public repo every "
        "message is published forever. If this phrase is legitimate here, edit the MARKERS list in "
        "implementations/protect-commit-privacy.py.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))

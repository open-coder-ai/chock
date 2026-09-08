#!/usr/bin/env python3
"""Print the first fenced bash block under README.md's `## Quick start` heading.

Used by CI (`quickstart` job in .github/workflows/ci.yml) to run the README's own
quick-start commands on a clean checkout, so the block CI runs is the block a reader
sees -- not a hand-copied approximation of it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HEADING = "## Quick start"
FENCE = "```"


class NoQuickStartHeadingError(ValueError):
    """README.md has no `## Quick start` heading."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"{path}: no {HEADING!r} heading found")


class NoBashBlockError(ValueError):
    """No fenced bash block was found under the Quick start heading."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"{path}: no fenced ```bash block found under {HEADING!r}")


def extract_first_bash_block(readme_text: str) -> str:
    """Return the contents of the first ```bash fence after the Quick start heading."""
    lines = readme_text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == HEADING)
    except StopIteration as exc:
        raise NoQuickStartHeadingError(Path("README.md")) from exc

    in_block = False
    block_lines: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip().startswith("## ") and not in_block:
            break  # next section reached before any bash fence was found
        if not in_block:
            if line.strip() == f"{FENCE}bash":
                in_block = True
            continue
        if line.strip() == FENCE:
            return "\n".join(block_lines) + "\n"
        block_lines.append(line)

    raise NoBashBlockError(Path("README.md"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("readme", nargs="?", default="README.md", type=Path)
    args = parser.parse_args(argv)

    block = extract_first_bash_block(args.readme.read_text())
    sys.stdout.write(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())

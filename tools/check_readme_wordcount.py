"""Word count of README.md excluding fenced code blocks and Markdown tables."""

from __future__ import annotations

import re
import sys
from pathlib import Path

LOW = 1200
HIGH = 1600


def stripped_words(text: str) -> int:
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    lines = [line for line in text.splitlines() if not re.match(r"^\s*\|.*\|\s*$", line)]
    text = "\n".join(lines)
    text = re.sub(r"<[^>]+>", "", text)
    return len(text.split())


def main() -> int:
    readme = Path(__file__).resolve().parent.parent / "README.md"
    count = stripped_words(readme.read_text())
    print(f"word count (excluding tables/code): {count}")
    if not LOW <= count <= HIGH:
        print(f"OUT OF RANGE: expected {LOW}-{HIGH}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

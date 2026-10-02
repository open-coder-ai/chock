"""Changelog fragments: `--check` validates changelog.d/*.md, `--assemble` builds the Unreleased section."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRAGMENT_DIR = "changelog.d"
CHANGELOG = "CHANGELOG.md"
HEADING = "## Unreleased"
NOT_FRAGMENTS = {"README.md"}


class MissingHeadingError(ValueError):
    def __init__(self) -> None:
        super().__init__(f"{CHANGELOG} has no '{HEADING}' heading")


def fragments(root: Path) -> list[Path]:
    """Fragment files, sorted by filename."""
    return sorted(p for p in (root / FRAGMENT_DIR).glob("*.md") if p.name not in NOT_FRAGMENTS)


def fragment_problems(path: Path) -> list[str]:
    """Why `path` is not a non-empty Markdown bullet list; empty when valid."""
    lines = path.read_text(encoding="utf-8").splitlines()
    body = [line for line in lines if line.strip()]
    if not body:
        return [f"{path.name}: empty"]
    problems = []
    if not body[0].startswith("- "):
        problems.append(f"{path.name}: must start with a '- ' bullet")
    for line in body:
        if line.startswith("#"):
            problems.append(f"{path.name}: headings belong in {CHANGELOG}, not in a fragment: {line[:40]!r}")
        elif not line.startswith(("- ", " ")):
            problems.append(f"{path.name}: line is neither a bullet nor an indented continuation: {line[:40]!r}")
    return problems


def touched_changelog(root: Path, base: str) -> bool:
    """True when the current branch differs from `base` in CHANGELOG.md."""
    out = subprocess.run(  # noqa: S603
        ["git", "-C", str(root), "diff", "--name-only", f"{base}...HEAD", "--", CHANGELOG],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(out.stdout.strip())


def check(root: Path, base: str | None = None) -> list[str]:
    problems = [msg for path in fragments(root) for msg in fragment_problems(path)]
    if base and touched_changelog(root, base):
        problems.append(f"{CHANGELOG} edited against {base}: add a {FRAGMENT_DIR}/<slug>.md fragment instead")
    return problems


def split_changelog(text: str) -> tuple[str, str, str]:
    """(before, unreleased entries, after) around the `## Unreleased` section."""
    lines = text.splitlines()
    try:
        start = lines.index(HEADING)
    except ValueError:
        raise MissingHeadingError from None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[:start]), "\n".join(lines[start + 1 : end]).strip(), "\n".join(lines[end:])


def assemble(root: Path) -> str:
    """The new changelog: existing Unreleased entries, then fragments sorted by filename."""
    before, existing, after = split_changelog((root / CHANGELOG).read_text(encoding="utf-8"))
    entries = [existing] if existing else []
    entries += [p.read_text(encoding="utf-8").strip() for p in fragments(root)]
    section = f"{HEADING}\n\n" + "\n".join(entries) + "\n"
    head = before.rstrip("\n") + "\n\n" if before else ""
    return head + section + ("\n" + after + "\n" if after else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="validate every fragment")
    mode.add_argument("--assemble", action="store_true", help="print the changelog with fragments folded in")
    parser.add_argument("--base", help="with --check: fail if CHANGELOG.md differs from this ref")
    parser.add_argument("--write", action="store_true", help="with --assemble: rewrite CHANGELOG.md in place")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.check:
        problems = check(args.root, args.base)
        sys.stderr.write("".join(f"{p}\n" for p in problems))
        return 1 if problems else 0
    text = assemble(args.root)
    if args.write:
        (args.root / CHANGELOG).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

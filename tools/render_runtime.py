#!/usr/bin/env python3
"""Render every runtime entry and the shared runtime from the templates into a directory, for semgrep on CI."""

from __future__ import annotations

import argparse
from pathlib import Path

from chock.gate import runtime_bundle


class NotEmptyError(FileExistsError):
    """The render target already holds files; a stale one would be scanned as if rendered."""

    def __init__(self, out: Path) -> None:
        super().__init__(f"{out}: not empty; render into a fresh directory")


def rendered() -> dict[str, str]:
    """{file name: text}: one entry per runtime agent plus the shared runtime -- the set the runtime goldens freeze."""
    files = {f"{agent}.py": runtime_bundle.render(agent) for agent in runtime_bundle.RUNTIME_AGENTS}
    files[runtime_bundle.SHARED_FILE] = runtime_bundle.render_shared()
    return files


def write(out: Path) -> list[Path]:
    """Write `rendered()` into `out`, which must be empty or absent; return the paths written."""
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise NotEmptyError(out)
    paths = []
    for name, text in sorted(rendered().items()):
        path = out / name
        path.write_text(text, encoding="utf-8", newline="\n")
        paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path, help="empty directory to render into")
    write(parser.parse_args(argv).out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

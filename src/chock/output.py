"""Shared console output: the `[WARN]`/`[ERROR]` prefix, say-once diagnostics, and text a console can show."""

from __future__ import annotations

import codecs
import sys
from typing import TextIO

# CodeQL (py/clear-text-logging-sensitive-data) flags both prints below by name-based
# heuristic, not by an actual credential flow: every caller passes a diagnostic string --
# an exception message, a file path, or an INDEX token-BUDGET count. The traced source is
# index/render.py's `max_tokens`/`main_tokens` (LLM context-window counts, not auth tokens)
# reaching index/cli.py's `warn(output.warning)`. compile/emitters/in_agent.py's
# PROJECT_DIR_TOKEN (a literal shell placeholder string, already ruled non-sensitive at its
# own definition: bandit S105) does not reach either function below -- it is only ever
# written to disk via write_generated_json, never logged. Audited every warn()/error() call
# site in src/; none carries credential material. T201/ERA001 are file-scoped in
# pyproject.toml: this is the designated output surface, and the codeql[...] suppression
# comments below read as commented-out code to ERA001.

#: Every non-ASCII character chock's own strings print, and its ASCII stand-in.
ASCII_FOR = str.maketrans(
    {
        "\u2026": "...",
        "\u2014": "--",
        "\u2013": "-",
        "\u2192": "->",
        "\u2190": "<-",
        "\u2264": "<=",
        "\u2265": ">=",
        "\u2208": " in ",
        "\u2227": " and ",
        "\u00a7": "s.",
        "\u2500": "-",
        "\u2502": "|",
        "\u251c": "+",
        "\u2514": "+",
        "\u200c": "",
        "\u200d": "",
        "\ufeff": "",
    }
)

_said: set[tuple[str, ...]] = set()


def unicode_ok(stream: TextIO | None = None) -> bool:
    """True only for a UTF stream: a legacy code page (cp1252) can encode U+2026 yet the console shows it as another letter."""
    encoding = getattr(stream if stream is not None else sys.stdout, "encoding", None)
    try:
        return codecs.lookup(encoding or "ascii").name.startswith("utf")
    except LookupError:
        return False


def legible(text: str, stream: TextIO | None = None) -> str:
    """`text` for `stream`: on a non-UTF stream chock's own symbols become ASCII; other text is the stream's to encode."""
    if text.isascii() or unicode_ok(stream):
        return text
    return text.translate(ASCII_FOR)


def ellipsis(stream: TextIO | None = None) -> str:
    return legible("\u2026", stream)


def first_time(key: tuple[str, ...]) -> bool:
    """True the first time this process asks about `key`; a fact is then said once per command."""
    if key in _said:
        return False
    _said.add(key)
    return True


def new_command() -> None:
    """Forget what was said: the once-per-command rule restarts with each `chock` command run in this process."""
    _said.clear()


def warn(message: str) -> None:
    # codeql[py/clear-text-logging-sensitive-data]
    print(f"[WARN] {legible(message, sys.stderr)}", file=sys.stderr)


def warn_once(key: tuple[str, ...], message: str) -> None:
    if first_time(key):
        warn(message)


def error(message: str) -> None:
    # codeql[py/clear-text-logging-sensitive-data]
    print(f"[ERROR] {legible(message, sys.stderr)}", file=sys.stderr)

"""Shared stderr diagnostics: one place owning the `[WARN]`/`[ERROR]` prefix convention."""

from __future__ import annotations

import sys

# CodeQL (py/clear-text-logging-sensitive-data) flags both prints below by name-based
# heuristic, not by an actual credential flow: every caller passes a diagnostic string --
# an exception message, a file path, or an INDEX token-BUDGET count. The heuristic fires on
# call sites like index/render.py's `max_tokens`/`main_tokens` (LLM context-window counts,
# not auth tokens) and compile/emitters/in_agent.py's PROJECT_DIR_TOKEN (a literal shell
# placeholder string, already ruled non-sensitive at its own definition (bandit S105)).
# Audited every warn()/error() call site in src/; none carries credential material.


def warn(message: str) -> None:
    print(f"[WARN] {message}", file=sys.stderr)  # noqa: T201 -- see comment above; lgtm[py/clear-text-logging-sensitive-data]


def error(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)  # noqa: T201 -- see comment above; lgtm[py/clear-text-logging-sensitive-data]

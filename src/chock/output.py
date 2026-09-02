"""Shared stderr diagnostics: one place owning the `[WARN]`/`[ERROR]` prefix convention."""

from __future__ import annotations

import sys

# CodeQL (py/clear-text-logging-sensitive-data) flags both prints below by name-based
# heuristic, not by an actual credential flow: every caller passes a diagnostic string --
# an exception message, a file path, or an INDEX token-BUDGET count. The traced source is
# index/render.py's `max_tokens`/`main_tokens` (LLM context-window counts, not auth tokens)
# reaching index/cli.py's `warn(output.warning)`. compile/emitters/in_agent.py's
# PROJECT_DIR_TOKEN (a literal shell placeholder string, already ruled non-sensitive at its
# own definition: bandit S105) does not reach either function below -- it is only ever
# written to disk via write_generated_json, never logged. Audited every warn()/error() call
# site in src/; none carries credential material. An inline `lgtm[...]` suppression was
# tried and did not clear the alert on re-scan (see plan/spine-a/reports/w50.md, org-plan);
# dismissing it needs a maintainer with Security-tab access this session does not have.


def warn(message: str) -> None:
    print(f"[WARN] {message}", file=sys.stderr)  # noqa: T201 -- the designated output surface


def error(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)  # noqa: T201 -- the designated output surface

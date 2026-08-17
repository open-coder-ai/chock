#!/usr/bin/env bash
# Repo-local (this repo only): fast conformance checks at commit time. CI re-runs the
# same checks on the pinned toolchain as the authority; this is the in-session
# approximation that turns a red CI round-trip into a five-second block. Skips with a
# warning when the dev tools are absent -- the CI backstop is what makes that honest.
set -eu

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

py=""
for c in python3 python py; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys" >/dev/null 2>&1; then
        py="$c"
        break
    fi
done
if [[ -z "$py" ]]; then
    echo "[WARN] conformance: no usable python on PATH; skipping (CI will run the checks)" >&2
    exit 0
fi
if ! "$py" -c "import pytest, ruff" >/dev/null 2>&1 && ! "$py" -m ruff --version >/dev/null 2>&1; then
    echo "[WARN] conformance: dev tools not installed; skipping (CI will run the checks)" >&2
    exit 0
fi

fail=0

echo "== conformance: ruff"
# check AND format --check: CI runs both, and a formatting failure slipped through
# when this hook mirrored only the first.
"$py" -m ruff check . || fail=1
"$py" -m ruff format --check . >/dev/null || { echo "ruff format --check failed; run: python -m ruff format ." >&2; fail=1; }

echo "== conformance: docs accuracy + emitter goldens"
PYTHONPATH=src "$py" -m pytest -q tests/test_docs_accuracy.py tests/test_emitter_stability.py || fail=1

if [[ "$fail" -ne 0 ]]; then
    echo "BLOCKED: conformance checks failed -- fix the source, never the check. CI runs the same checks on the pinned toolchain." >&2
fi
exit "$fail"

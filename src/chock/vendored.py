"""Vendored-runtime inventory and drift detection.

Lives below both `lock` and `scaffold.recompile` so integrity checks can compare
the vendored copies against the source each was rendered from, without importing the
orchestrator that writes them.
"""

from __future__ import annotations

from pathlib import Path

#: Files vendored into `.chock/bin/`, and how to render the bytes each should currently be.
#: All are executed on an adopter's machine: `gate.py` runs every declarative gate, and each
#: per-agent runtime feeds that agent's own dialect of a tool-use/session-start payload to a
#: guard (agentseam's bundle plumbing plus chock's own handler -- see
#: `gate/runtime_bundle.py`) -- so a tampered copy of any of them belongs to the same drift
#: guarantee. `gate.py` is a static packaged file; the per-agent runtimes are rendered, not
#: copied, so "the source" for those is a function call, not a file read.
VENDORED_RUNTIMES = {
    "gate.py": ("static", ("chock.gate", "runner.py")),
    "claude_code.py": ("bundle", "claude_code"),
    "cursor.py": ("bundle", "cursor"),
    "vscode_copilot.py": ("bundle", "vscode_copilot"),
}


def _expected_bytes(kind: str, source) -> bytes | None:
    if kind == "static":
        import importlib.resources as resources

        package, source_name = source
        try:
            return resources.files(package).joinpath(source_name).read_bytes()
        except (FileNotFoundError, ModuleNotFoundError, OSError):  # pragma: no cover - packaging failure
            return None
    from chock.gate import runtime_bundle

    return runtime_bundle.render(source).encode("utf-8")


def vendored_differences(repo_root: Path | str) -> list[str]:
    """Report vendored runtimes that no longer match the source they were rendered from.

    This is the cheapest bypass in the whole system and nothing detected it. Replacing the
    body of `run()` in `.chock/bin/gate.py` with `return 0` disables every gate in
    the repo at once -- a secret and a direct commit to `main` both went through while the
    installed pre-commit hook printed "[PASS] All checks passed." `validate`, `verify`,
    `eval` and `recompile --check` all exited 0.

    Only files already present are compared. A repo that has compiled but never installed
    hooks has no `claude_code.py`, and that is not drift.
    """
    repo_root = Path(repo_root)
    bin_dir = repo_root / ".chock" / "bin"
    diffs: list[str] = []
    for name, (kind, source) in sorted(VENDORED_RUNTIMES.items()):
        vendored = bin_dir / name
        if not vendored.exists():
            continue
        expected = _expected_bytes(kind, source)
        if expected is None:
            continue
        if vendored.read_bytes() != expected:
            diffs.append(f"differs: bin/{name}")
    return diffs

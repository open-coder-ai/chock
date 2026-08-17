"""Vendored-runtime inventory and drift detection.

Lives below both `lock` and `scaffold.recompile` so integrity checks can compare
the vendored copies against their packaged sources without importing the
orchestrator that writes them.
"""

from __future__ import annotations

from pathlib import Path

#: Files vendored verbatim into `.chock/bin/`, and the packaged source each is a copy
#: of. All are executed on an adopter's machine: `gate.py` runs every declarative gate,
#: `pretooluse.py` feeds Claude's tool payload to a guard, and `sessionstart.py` arms a
#: fresh clone's git hooks -- so a tampered copy of any of them belongs to the same
#: drift guarantee.
VENDORED_RUNTIMES = {
    "gate.py": ("chock.gate", "runner.py"),
    "pretooluse.py": ("chock.gate", "pretooluse.py"),
    "sessionstart.py": ("chock.gate", "sessionstart.py"),
}


def vendored_differences(repo_root: Path | str) -> list[str]:
    """Report vendored runtimes that no longer match the source they were copied from.

    This is the cheapest bypass in the whole system and nothing detected it. Replacing the
    body of `run()` in `.chock/bin/gate.py` with `return 0` disables every gate in
    the repo at once -- a secret and a direct commit to `main` both went through while the
    installed pre-commit hook printed "[PASS] All checks passed." `validate`, `verify`,
    `eval` and `recompile --check` all exited 0.

    Only files already present are compared. A repo that has compiled but never installed
    hooks has no `pretooluse.py`, and that is not drift.
    """
    import importlib.resources as resources

    repo_root = Path(repo_root)
    bin_dir = repo_root / ".chock" / "bin"
    diffs: list[str] = []
    for name, (package, source_name) in sorted(VENDORED_RUNTIMES.items()):
        vendored = bin_dir / name
        if not vendored.exists():
            continue
        try:
            source = resources.files(package).joinpath(source_name).read_bytes()
        except (FileNotFoundError, ModuleNotFoundError, OSError):  # pragma: no cover - packaging failure
            continue
        if vendored.read_bytes() != source:
            diffs.append(f"differs: bin/{name}")
    return diffs

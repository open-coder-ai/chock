"""Vendored-runtime inventory and drift detection."""

from __future__ import annotations

from pathlib import Path

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
    """Report vendored runtimes that no longer match the source they were rendered from."""
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

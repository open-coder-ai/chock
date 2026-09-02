"""Vendored-runtime inventory and drift detection."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from chock.gate import runtime_bundle
from chock.vendors import in_agent_vendors

VENDORED_RUNTIMES = {
    "gate.py": ("static", ("chock.gate", "runner.py")),
    **{f"{agent}.py": ("bundle", agent) for agent in in_agent_vendors()},
}


def _expected_bytes(kind: str, source) -> bytes | None:
    if kind == "static":
        package, source_name = source
        try:
            return resources.files(package).joinpath(source_name).read_bytes()
        except (FileNotFoundError, ModuleNotFoundError, OSError):  # pragma: no cover - packaging failure
            return None
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

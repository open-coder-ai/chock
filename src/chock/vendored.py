"""Vendored-runtime inventory and drift detection."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from chock.emit import write_generated
from chock.gate import runtime_bundle
from chock.gate.assemble import runner_source
from chock.gate.build import vendor_runner
from chock.vendors import in_agent_vendors

VENDORED_RUNTIMES = {
    "gate.py": ("assembled", None),
    "chock_session.py": ("static", ("chock.gate", "session_reader.py")),
    runtime_bundle.SHARED_FILE: ("shared", None),
    **{f"{agent}.py": ("bundle", agent) for agent in in_agent_vendors()},
}


def expected_runtime(kind: str, source) -> bytes | None:
    """The bytes a vendored runtime of `kind` is rendered as now; None on a packaging failure."""
    if kind == "assembled":
        try:
            return runner_source().encode("utf-8")
        except OSError:  # pragma: no cover - packaging failure
            return None
    if kind == "static":
        package, source_name = source
        try:
            return resources.files(package).joinpath(source_name).read_bytes()
        except (FileNotFoundError, ModuleNotFoundError, OSError):  # pragma: no cover - packaging failure
            return None
    if kind == "shared":
        return runtime_bundle.render_shared().encode("utf-8")
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
        expected = expected_runtime(kind, source)
        if expected is None:
            continue
        if vendored.read_bytes() != expected:
            diffs.append(f"differs: bin/{name}")
    return diffs


def refresh_vendored(repo_root: Path | str) -> None:
    """Rewrite every committed runtime `vendored_differences` reports, so `sync --check` passes after `sync`."""
    repo_root = Path(repo_root)
    for diff in vendored_differences(repo_root):
        name = diff.removeprefix("differs: bin/")
        kind, source = VENDORED_RUNTIMES[name]
        if kind == "assembled":
            vendor_runner(repo_root / ".chock")
        elif (expected := expected_runtime(kind, source)) is not None:
            write_generated(repo_root / ".chock" / "bin" / name, expected.decode("utf-8"))

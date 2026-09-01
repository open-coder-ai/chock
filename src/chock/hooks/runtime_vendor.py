"""Write a per-agent vendored runtime into `.chock/bin/`."""

from __future__ import annotations

from pathlib import Path

from chock.gate import runtime_bundle


def runtime_rel(agent: str) -> Path:
    return Path(".chock") / "bin" / f"{agent}.py"


def vendor_runtime(repo_root: Path, agent: str) -> Path:
    """Write `agent`'s self-contained runtime into `.chock/bin/`. Returns the path written."""
    dest = Path(repo_root) / runtime_rel(agent)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(runtime_bundle.render(agent), encoding="utf-8")
    try:
        dest.chmod(0o755)
    except OSError:
        pass
    return dest

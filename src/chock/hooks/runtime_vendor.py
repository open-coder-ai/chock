"""Write a per-agent vendored runtime into `.chock/bin/`."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

from chock.gate import runtime_bundle
from chock.resources import package_data_dir

#: Basenames chock has written under `.chock/bin/` before the current per-vendor naming
#: (`pretooluse.py` served claude_code's PreToolUse and cursor's beforeShellExecution;
#: `sessionstart.py` served claude_code's SessionStart). A committed config from before
#: the rename still points at these; sync must recognise them as its own, not as a
#: stranger's script that happens to live in a chock-owned directory.
LEGACY_RUNTIME_BASENAMES: tuple[str, ...] = tuple(
    json.loads(package_data_dir("chock", "hooks", "data").joinpath("legacy_runtime_basenames.json").read_text())
)


def runtime_rel(agent: str) -> Path:
    return Path(".chock") / "bin" / f"{agent}.py"


def owned_markers(agent: str) -> tuple[str, ...]:
    """Every `.chock/bin/` command substring that identifies a hook entry as `agent`'s own."""
    current = f"/{runtime_rel(agent).as_posix()}"
    legacy = tuple(f"/.chock/bin/{name}" for name in LEGACY_RUNTIME_BASENAMES)
    return (current, *legacy)


def vendor_runtime(repo_root: Path, agent: str) -> Path:
    """Write `agent`'s self-contained runtime into `.chock/bin/`. Returns the path written."""
    dest = Path(repo_root) / runtime_rel(agent)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(runtime_bundle.render(agent), encoding="utf-8")
    with contextlib.suppress(OSError):
        dest.chmod(0o755)
    return dest

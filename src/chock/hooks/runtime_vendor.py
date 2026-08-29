"""Write a per-agent vendored runtime into `.chock/bin/`.

One tiny module shared by every installer that needs to vendor a runtime file
(`pretooluse_install`, `cursor_install`, `agenthooks_install`, `sessionstart_install`), so
the render-and-chmod step exists in exactly one place rather than four copies.
"""

from __future__ import annotations

from pathlib import Path

from chock.gate import runtime_bundle

#: agent -> the file its vendored runtime is written as under `.chock/bin/`.
RUNTIME_FILENAME = {
    "claude_code": "claude_code.py",
    "cursor": "cursor.py",
    "vscode_copilot": "vscode_copilot.py",
}


def runtime_rel(agent: str) -> Path:
    return Path(".chock") / "bin" / RUNTIME_FILENAME[agent]


def vendor_runtime(repo_root: Path, agent: str) -> Path:
    """Write `agent`'s self-contained runtime into `.chock/bin/`. Returns the path written."""
    dest = Path(repo_root) / runtime_rel(agent)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(runtime_bundle.render(agent), encoding="utf-8")
    try:
        dest.chmod(0o755)
    except OSError:
        pass  # best-effort: chmod is a no-op/denied on Windows; invoked as `python <path>`
    return dest

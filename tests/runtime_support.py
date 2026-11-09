"""A rendered runtime as it ships: the entry, and beside it the shared runtime it loads."""

from __future__ import annotations

from pathlib import Path

from chock.gate import runtime_bundle


def write_runtime(path: Path, agent: str) -> Path:
    """Write `agent`'s entry at `path` and the shared runtime beside it; `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(runtime_bundle.render(agent), encoding="utf-8")
    path.with_name(runtime_bundle.SHARED_FILE).write_text(runtime_bundle.render_shared(), encoding="utf-8")
    return path


def load_runtime(folder: Path, agent: str) -> dict:
    """`agent`'s entry run in-process from `folder` (its `main` not called): its namespace."""
    path = write_runtime(folder / f"{agent}.py", agent)
    namespace: dict = {"__name__": "chock_runtime_under_test", "__file__": str(path)}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)  # noqa: S102 -- the rendered runtime is the unit under test
    return namespace


#: What a stand-in runtime runs first so the launcher reads its start marker (the real entries carry `start_marker.py.tmpl`).
START_MARKER_STUB = (
    "import os, sys\n"
    "if 'CHOCK_START_FD' in os.environ:\n"
    "    os.write(int(os.environ['CHOCK_START_FD']), b'chock-python')\n"
    "    os.close(int(os.environ['CHOCK_START_FD']))\n"
)

"""A FIFO or symlink planted where chock logs never blocks a hook: the writers refuse it before opening anything."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from chock.gate import session_log
from chock.gate.runner import journal

pytestmark = pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are a POSIX construct")

_TIMEOUT = 20


def _call(code: str, *args: str) -> subprocess.CompletedProcess:
    """Run `code` in a fresh interpreter, so a blocked open is a timeout and not a hung test."""
    return subprocess.run(
        [sys.executable, "-c", code, *args], capture_output=True, text=True, timeout=_TIMEOUT, check=False
    )


_APPEND = (
    "import sys\nfrom chock.gate.runner import journal\n"
    "try:\n    journal.log_append(sys.argv[1], {'policy_id': 'p'})\nexcept OSError:\n    print('refused')\n"
)
_SESSION = (
    "import sys\nfrom pathlib import Path\nfrom chock.gate import session_log\n"
    "session_log._append_bounded(Path(sys.argv[1]), '{}', {'ts': 'x', 'phase': 'pre', 'tool_use_id': 'a'})\nprint('returned')\n"
)


@pytest.mark.parametrize("name", ["gate-events.jsonl", "gate-events.jsonl.lock", "gate-events.1.jsonl"])
def test_log_append_refuses_a_fifo_where_chock_writes(tmp_path: Path, name: str) -> None:
    log = tmp_path / ".chock" / "log"
    log.mkdir(parents=True)
    os.mkfifo(log / name)
    done = _call(_APPEND, str(log / "gate-events.jsonl"))
    assert done.stdout.strip() == "refused"


def test_log_append_refuses_a_fifo_in_place_of_the_log_directory(tmp_path: Path) -> None:
    (tmp_path / ".chock").mkdir()
    os.mkfifo(tmp_path / ".chock" / "log")
    assert _call(_APPEND, str(tmp_path / ".chock" / "log" / "gate-events.jsonl")).stdout.strip() == "refused"


def test_log_append_refuses_a_symlinked_log(tmp_path: Path) -> None:
    log = tmp_path / ".chock" / "log"
    log.mkdir(parents=True)
    target = tmp_path / "elsewhere"
    target.write_text("", encoding="utf-8")
    (log / "gate-events.jsonl").symlink_to(target)
    assert _call(_APPEND, str(log / "gate-events.jsonl")).stdout.strip() == "refused"
    assert target.read_text(encoding="utf-8") == ""


def test_log_append_still_writes_a_regular_log(tmp_path: Path) -> None:
    path = tmp_path / ".chock" / "log" / "gate-events.jsonl"
    journal.log_append(path, {"policy_id": "p"})
    assert '"policy_id": "p"' in path.read_text(encoding="utf-8")
    assert oct(path.stat().st_mode & 0o777) == "0o600"


@pytest.mark.parametrize("name", ["s1.jsonl", "s1.tmp"])
def test_the_session_log_skips_a_fifo(tmp_path: Path, name: str) -> None:
    state = tmp_path / ".chock" / "state"
    state.mkdir(parents=True)
    os.mkfifo(state / name)
    assert _call(_SESSION, str(state / "s1.jsonl")).stdout.strip() == "returned"


def test_the_session_log_skips_a_symlinked_log(tmp_path: Path) -> None:
    state = tmp_path / ".chock" / "state"
    state.mkdir(parents=True)
    target = tmp_path / "elsewhere"
    target.write_text("", encoding="utf-8")
    (state / "s1.jsonl").symlink_to(target)
    session_log._append_bounded(state / "s1.jsonl", "{}", {"ts": "x", "phase": "pre", "tool_use_id": "a"})
    assert target.read_text(encoding="utf-8") == ""


def test_the_session_log_trim_writes_a_private_file(tmp_path: Path) -> None:
    path = session_log.session_log_path(tmp_path, "s1")
    path.parent.mkdir(parents=True)
    path.write_text("".join(f'{{"n": {n}}}\n' for n in range(session_log.SESSION_MAX_ENTRIES)), encoding="utf-8")
    event = SimpleNamespace(
        event="pre_tool", tool="Bash", command=None, path=None, session_id="s1", tool_use_id="c9", raw={}, output=None
    )
    session_log.session_record(tmp_path, event, "pre")
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert len(path.read_text(encoding="utf-8").splitlines()) == session_log.SESSION_MAX_ENTRIES

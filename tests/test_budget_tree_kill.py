"""run_tree kills a timed-out child's whole tree; a member's deadline stays in its own thread."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

import pytest

from chock.gate import budget

_SPAWNER = (
    "import subprocess, sys, time\n"
    "kid = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "print(kid.pid, flush=True)\n"
    "time.sleep(60)\n"
)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@pytest.mark.skipif(os.name == "nt", reason="the POSIX process-group kill; Windows is covered in CI by taskkill /T")
def test_timeout_kills_the_grandchild_too(tmp_path):
    pidfile = tmp_path / "pid"
    script = _SPAWNER.replace("print(kid.pid, flush=True)", f"open({str(pidfile)!r}, 'w').write(str(kid.pid))")
    with pytest.raises(subprocess.TimeoutExpired):
        budget.run_tree([sys.executable, "-c", script], capture_output=True, text=True, timeout=2)
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 5
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(pid)


def test_run_tree_matches_run_for_a_normal_child():
    done = budget.run_tree(
        [sys.executable, "-c", "import sys; print(sys.stdin.read().upper()); sys.exit(3)"],
        input="ok",
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert (done.returncode, done.stdout.strip()) == (3, "OK")


def test_member_deadline_is_per_thread_and_defaults_to_the_engine_budget():
    seen: dict[str, float] = {}

    def member(name: str, instant: float) -> None:
        budget.MEMBER_DEADLINE.set(instant)
        time.sleep(0.05)
        seen[name] = budget.engine_deadline()

    threads = [threading.Thread(target=member, args=(n, i)) for n, i in (("a", 111.0), ("b", 222.0))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert seen == {"a": 111.0, "b": 222.0}
    assert budget.MEMBER_DEADLINE.get() is None
    assert budget.engine_deadline() - time.monotonic() == pytest.approx(budget.ENGINE_BUDGET_SECONDS, abs=1)


@pytest.mark.skipif(os.name == "nt", reason="the POSIX process-group kill; Windows uses taskkill /T")
def test_close_judge_kills_the_judges_own_children(tmp_path):
    pidfile = tmp_path / "pid"
    script = _SPAWNER.replace("print(kid.pid, flush=True)", f"open({str(pidfile)!r}, 'w').write(str(kid.pid))")
    script += "\n"
    judge = budget.pattern_judge()
    judge["argv"] = [sys.executable, "-c", f"print({budget.PATTERN_JUDGE_READY!r}, flush=True)\n{script}"]
    assert budget._ensure_judge(judge) is None
    deadline = time.monotonic() + 5
    while not pidfile.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    pid = int(pidfile.read_text())
    budget.close_judge(judge)
    deadline = time.monotonic() + 5
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(pid)

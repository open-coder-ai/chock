"""The multi-policy hook core: pinned index, per-member deadline and fault, ordered verdicts, thread-local last state."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time

import pytest

from chock.gate import budget, guard_runner, multi


def _index(tmp_path, members):
    path = tmp_path / "index.json"
    path.write_text(json.dumps({"members": members}), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_index_loads_only_with_its_pin(tmp_path):
    path, pin = _index(tmp_path, [{"argv": ["--guard", "a"], "timeout": 5, "files": {}}])
    assert multi.load_index(str(path), pin, tmp_path)[1] is None
    for bad in ("", "0" * 64):
        assert multi.load_index(str(path), bad, tmp_path)[0] is None


def test_index_refuses_a_member_file_that_drifted(tmp_path):
    (tmp_path / "g.py").write_text("x", encoding="utf-8")
    path, pin = _index(tmp_path, [{"argv": ["--guard", "g.py"], "timeout": 5, "files": {"g.py": "0" * 64}}])
    members, why = multi.load_index(str(path), pin, tmp_path)
    assert members is None
    assert "g.py" in why


def test_index_refuses_missing_and_unparseable(tmp_path):
    assert multi.load_index(str(tmp_path / "none.json"), "0" * 64, tmp_path)[0] is None
    path = tmp_path / "bad.json"
    path.write_text("{", encoding="utf-8")
    assert multi.load_index(str(path), hashlib.sha256(b"{").hexdigest(), tmp_path)[0] is None


def test_hung_member_refuses_itself_and_the_others_report():
    members = [
        {"argv": ["--guard", "fast"], "timeout": 5},
        {"argv": ["--guard", "hung"], "timeout": 0.3},
        {"argv": ["--guard", "boom"], "timeout": 5},
    ]
    stop = threading.Event()

    def judge(argv):
        if argv[1] == "hung":
            stop.wait(10)
        if argv[1] == "boom":
            raise RuntimeError("bad")

    started = time.monotonic()
    verdicts = multi.run_members(members, judge)
    stop.set()
    assert time.monotonic() - started < 3
    assert verdicts[0] is None
    assert verdicts[1][0] == "deny"
    assert "hung" in verdicts[1][1]
    assert verdicts[2][0] == "deny"
    assert "RuntimeError" in verdicts[2][1]


def test_each_member_sees_only_its_own_deadline():
    seen = {}

    def judge(argv):
        seen[argv[1]] = budget.MEMBER_DEADLINE.get()

    members = [{"argv": ["--guard", "a"], "timeout": 1}, {"argv": ["--guard", "b"], "timeout": 100}]
    multi.run_members(members, judge)
    assert seen["b"] - seen["a"] > 50


def test_combine_orders_deny_then_ask_then_warn_in_index_order():
    assert multi.combine([None, None]) is None
    assert multi.combine([("warn", "w1"), None, ("warn", "w2")]) == ("warn", "w1\nw2")
    assert multi.combine([("warn", "w"), ("escalate", "e")]) == ("escalate", "e")
    assert multi.combine([("escalate", "e"), ("deny", "d1"), ("deny", "d2")]) == ("deny", "d1\nd2")


def test_last_state_is_per_thread():
    budget.last_state(guard_runner.GUARD_LAST)["code"] = 7
    other = {}
    thread = threading.Thread(target=lambda: other.update(budget.last_state(guard_runner.GUARD_LAST)))
    thread.start()
    thread.join()
    assert other == {}
    assert budget.last_state(guard_runner.GUARD_LAST)["code"] == 7


def test_a_member_that_exits_refuses_itself_at_once():
    def judge(argv):
        if argv[1] == "quits":
            raise SystemExit(2)

    members = [{"argv": ["--guard", "quits"], "timeout": 30}, {"argv": ["--guard", "fine"], "timeout": 30}]
    started = time.monotonic()
    verdicts = multi.run_members(members, judge)
    assert time.monotonic() - started < 3
    assert verdicts[0][0] == "deny"
    assert "SystemExit" in verdicts[0][1]
    assert "quits" in verdicts[0][1]
    assert "Refusing rather than reporting an allow" in verdicts[0][1]
    assert verdicts[1] is None


@pytest.mark.parametrize("body", ['{"members": []}', '{"members": {}}', '{"members": null}', "{}"])
def test_an_index_with_no_members_refuses(tmp_path, body):
    path = tmp_path / "index.json"
    path.write_text(body, encoding="utf-8")
    members, why = multi.load_index(str(path), hashlib.sha256(path.read_bytes()).hexdigest(), tmp_path)
    assert members is None
    assert why


@pytest.mark.skipif(os.name == "nt", reason="the POSIX process-group kill; Windows uses taskkill /T")
def test_leaving_ends_the_tree_of_a_member_hung_past_its_deadline(tmp_path, monkeypatch):
    pidfile = tmp_path / "pid"
    script = f"import os, time\nopen({str(pidfile)!r}, 'w').write(str(os.getpid()))\ntime.sleep(60)\n"

    def judge(argv):
        budget.run_tree([sys.executable, "-c", script], capture_output=True, text=True)

    verdicts = multi.run_members([{"argv": ["--guard", "hung"], "timeout": 1.0}], judge)
    assert verdicts[0][0] == "deny"
    pid = int(pidfile.read_text())
    assert _alive(pid)
    exits = []
    monkeypatch.setattr(multi.os, "_exit", exits.append)
    multi.flush_and_exit(2)
    assert exits == [2]
    deadline = time.monotonic() + 5
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(pid)
    assert budget.LIVE_TREES == {}


def test_members_get_no_stdin_and_never_write_to_the_streams(capfd):
    seen = {}

    def judge(argv):
        seen[argv[1]] = sys.stdin.read()
        print("to stdout")
        print("to stderr", file=sys.stderr)

    members = [{"argv": ["--guard", "a"], "timeout": 5}, {"argv": ["--guard", "b"], "timeout": 5}]
    real = sys.stdin, sys.stdout, sys.stderr
    multi.run_members(members, judge)
    assert (sys.stdin, sys.stdout, sys.stderr) == real
    assert seen == {"a": "", "b": ""}
    out, err = capfd.readouterr()
    assert out == ""
    assert err == ""


def test_degrade_and_can_ask_apply_per_member_before_combining():
    members = [{"argv": ["--guard", name], "timeout": 5} for name in ("ask", "warn")]
    verdicts = {"ask": ("escalate", "asks"), "warn": ("warn", "warns")}

    def run(**kind):
        return multi.run_members(members, lambda argv: verdicts[argv[1]], **kind)

    assert multi.combine(run()) == ("escalate", "asks")
    assert multi.combine(run(can_ask=False)) == ("deny", "asks")
    assert run(warn_speaks=False) == [("escalate", "asks"), None]
    only_warn = multi.run_members(members[1:], lambda argv: verdicts[argv[1]], warn_speaks=False)
    assert multi.combine(only_warn) is None
    assert multi.combine(multi.run_members(members[1:], lambda argv: verdicts[argv[1]])) == ("warn", "warns")


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True

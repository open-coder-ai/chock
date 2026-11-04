"""The multi-policy hook core: pinned index, per-member deadline and fault, ordered verdicts, thread-local last state."""

from __future__ import annotations

import hashlib
import json
import threading
import time

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

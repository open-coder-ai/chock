"""The per-session tool-call log: what is recorded, what never is, how it is bounded, and how a script reads it."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

from tool_call_support import SCRIPT, fire, log_lines, make_repo, pre_payload, tool_call_gate

from chock.gate import session_log, session_reader
from chock.hooks.in_agent_install import install_hooks
from chock.hooks.runtime_vendor import sync_session_helper
from chock.scaffold.gitrules import ensure_git_rules

GATE = ".chock/compiled/guard-tools/pre-tool-use/tool-call-gate.json"
SECRET_ENV = "hunter2-not-a-real-secret"  # pragma: allowlist secret -- the string under test


def _event(name="pre_tool", tool="Bash", tool_input=None, session="s1", call="c1"):
    raw = {"tool_input": tool_input or {}}
    return SimpleNamespace(
        event=name, tool=tool, command=None, path=None, session_id=session, tool_use_id=call, raw=raw, output=None
    )


def _lines(root: Path, session="s1") -> list[dict]:
    path = session_log.session_log_path(root, session)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --- what a record holds --------------------------------------------------------------------------


def test_a_record_has_the_documented_fields(tmp_path: Path) -> None:
    session_log.session_record(tmp_path, _event(tool_input={"command": "make test"}), "pre")
    (record,) = _lines(tmp_path)
    assert set(record) == {"ts", "session_id", "phase", "tool", "input", "outcome", "tool_use_id"}
    assert record["session_id"] == "s1"
    assert record["phase"] == "pre"
    assert record["tool"] == "Bash"
    assert record["input"] == {"command": "make test"}
    assert record["outcome"] is None
    assert record["ts"].endswith("Z")


def test_only_path_command_and_url_are_summarised_never_content_or_env_values(tmp_path: Path) -> None:
    write = _event(tool="Write", tool_input={"file_path": "src/a.py", "content": "SECRET BODY", "new_string": "x"})
    session_log.session_record(tmp_path, write, "pre")
    bash = _event(
        tool_input={"command": f"API_KEY={SECRET_ENV} TOKEN=abc make deploy --flag=1\nsecond line"}, call="c2"
    )
    session_log.session_record(tmp_path, bash, "pre")
    fetch = _event(tool="WebFetch", tool_input={"url": "https://u:p@example.com/a?token=zzz#frag"}, call="c3")
    session_log.session_record(tmp_path, fetch, "pre")
    text = session_log.session_log_path(tmp_path, "s1").read_text(encoding="utf-8")
    assert "SECRET BODY" not in text and SECRET_ENV not in text and "second line" not in text
    assert "token=zzz" not in text and "u:p" not in text
    records = _lines(tmp_path)
    assert records[0]["input"] == {"path": "src/a.py"}
    assert records[1]["input"] == {"command": "API_KEY=*** TOKEN=*** make deploy --flag=1"}
    assert records[2]["input"] == {"url": "https://example.com/a"}


def test_a_session_id_cannot_leave_the_state_directory(tmp_path: Path) -> None:
    session_log.session_record(tmp_path, _event(session="../../evil/../x"), "pre")
    written = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.jsonl"))
    assert written == [".chock/state/evil..x.jsonl"]
    assert session_log.session_id_of(_event(session=None)) == "unknown"


def test_outcome_comes_from_the_payload_and_a_failure_event(tmp_path: Path) -> None:
    ok = _event("post_tool")
    ok.raw["tool_response"] = {"stdout": "fine"}
    bad = _event("post_tool")
    bad.raw["tool_response"] = {"is_error": True}
    assert session_log.session_outcome(ok) == "ok"
    assert session_log.session_outcome(bad) == "error"
    assert session_log.session_outcome(_event("tool_failure")) == "error"
    assert session_log.session_outcome(_event("pre_tool")) is None


# --- bounds ---------------------------------------------------------------------------------------


def test_the_log_keeps_the_last_500_entries(tmp_path: Path) -> None:
    for i in range(session_log.SESSION_MAX_ENTRIES + 25):
        session_log.session_record(tmp_path, _event(tool_input={"command": f"c{i}"}, call=f"id{i}"), "pre")
    records = _lines(tmp_path)
    assert len(records) == session_log.SESSION_MAX_ENTRIES
    assert records[-1]["input"]["command"] == f"c{session_log.SESSION_MAX_ENTRIES + 24}"
    assert records[0]["input"]["command"] == "c25"


def test_logs_older_than_seven_days_are_pruned_and_recent_ones_kept(tmp_path: Path) -> None:
    session_log.session_record(tmp_path, _event(session="old"), "pre")
    session_log.session_record(tmp_path, _event(session="recent"), "pre")
    old = session_log.session_log_path(tmp_path, "old")
    aged = time.time() - session_log.SESSION_PRUNE_SECONDS - 60
    os.utime(old, (aged, aged))
    session_log.session_record(tmp_path, _event(session="now"), "pre")
    assert not old.exists()
    assert session_log.session_log_path(tmp_path, "recent").exists()


def test_one_call_logged_by_two_hooks_appears_once(tmp_path: Path) -> None:
    event = _event(call="same")
    session_log.session_record(tmp_path, event, "pre")
    session_log.session_record(tmp_path, event, "pre")
    session_log.session_record(tmp_path, event, "post", "ok")
    assert [r["phase"] for r in _lines(tmp_path)] == ["pre", "post"]


def test_a_repeated_call_with_a_new_id_is_a_new_record(tmp_path: Path) -> None:
    for call in ("a", "b", "c"):
        session_log.session_record(tmp_path, _event(tool_input={"command": "make"}, call=call), "pre")
    assert len(_lines(tmp_path)) == 3


def test_recording_never_raises(tmp_path: Path) -> None:
    blocker = tmp_path / ".chock"
    blocker.write_text("a file where the directory should be", encoding="utf-8")
    session_log.session_record(tmp_path, _event(), "pre")


# --- the hooks write it, the script reads it --------------------------------------------------------


def test_a_script_gate_sees_prior_calls_and_a_failed_fetch(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, tool_call_gate(script=True), script=SCRIPT)
    install_hooks(repo, "claude_code")
    url = "https://a.example/page"
    fire(repo, ["--tool-call", GATE], pre_payload(repo, "mcp__Firecrawl__firecrawl_scrape", {"url": url + "?k=v"}))
    post = {
        **pre_payload(repo, "mcp__Firecrawl__firecrawl_scrape", {"url": url}),
        "hook_event_name": "PostToolUseFailure",
    }
    fire(repo, ["--record", GATE], post)
    fire(repo, ["--tool-call", GATE], pre_payload(repo, "Read", {"file_path": "src/a.py"}, call="t2"))
    fire(repo, ["--tool-call", GATE], pre_payload(repo, "mcp__Firecrawl__firecrawl_scrape", {"url": url}, call="t3"))

    seen = json.loads((repo / "payload.json").read_text())["session"]
    records = session_reader.prior(seen)
    assert session_reader.failed(records, tool="mcp__Firecrawl__firecrawl_scrape", url=url)
    assert session_reader.count(records, tool="Read", phase=session_reader.PRE, path="src/a.py") == 1
    assert session_reader.count(records, tool="mcp__Firecrawl__firecrawl_scrape", phase=session_reader.PRE) == 1
    assert [r["phase"] for r in log_lines(repo)].count("post") == 1


def test_a_successful_post_tool_use_is_recorded_ok_and_silently(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, tool_call_gate(script=True), script=SCRIPT)
    install_hooks(repo, "claude_code")
    post = {**pre_payload(repo, "WebFetch", {"url": "https://a.example/x?s=1"}), "hook_event_name": "PostToolUse"}
    post["tool_response"] = {"is_error": False}
    proc = fire(repo, ["--record", GATE], post)
    assert proc.returncode == 0 and proc.stdout == ""
    (record,) = log_lines(repo)
    assert (record["phase"], record["outcome"], record["input"]) == ("post", "ok", {"url": "https://a.example/x"})


def test_a_call_the_gate_blocked_is_logged_as_blocked(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, tool_call_gate(script=True), script=SCRIPT)
    install_hooks(repo, "claude_code")
    fire(
        repo,
        ["--tool-call", GATE],
        pre_payload(repo, "mcp__Firecrawl__firecrawl_scrape", {"url": "https://x.example/blocked"}),
    )
    (record,) = log_lines(repo)
    assert record["outcome"] == "blocked"


def test_a_regex_gate_reads_no_session_and_writes_none(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, tool_call_gate())
    install_hooks(repo, "claude_code")
    fire(repo, ["--tool-call", GATE], pre_payload(repo, "WebFetch", {"url": "https://ok.example"}))
    assert not (repo / ".chock" / "state").exists()


def test_a_write_gate_script_is_handed_the_session(tmp_path: Path) -> None:
    script = "import json, sys\np = json.load(sys.stdin)\nopen(p['repo_root'] + '/s.json', 'w').write(json.dumps(p['session']))\n"
    gate = {"kind": "script", "on": ["commit", "tool_use"], "params": {"script": "judge.py"}}
    repo = make_repo(tmp_path, gate, script=script)
    install_hooks(repo, "claude_code")
    write = pre_payload(repo, "Write", {"file_path": "a.py", "content": "x = 1\n"})
    fire(repo, ["--gate", GATE.replace("tool-call-gate", "gate")], write)
    session = json.loads((repo / "s.json").read_text())
    assert session["id"] == "sess-1" and session["log_path"].endswith(".chock/state/sess-1.jsonl")


# --- the reader helper, gitignore and vendoring ------------------------------------------------------


def test_the_reader_tolerates_a_missing_or_damaged_log(tmp_path: Path) -> None:
    assert session_reader.entries(tmp_path / "nope.jsonl") == []
    assert session_reader.entries(None) == []
    damaged = tmp_path / "d.jsonl"
    damaged.write_text('{"tool": "A"}\nnot json\n[1]\n', encoding="utf-8")
    assert session_reader.entries(damaged) == [{"tool": "A"}]


def test_the_reader_refuses_an_unknown_input_field() -> None:
    try:
        session_reader.matching([], colour="red")
    except TypeError as exc:
        assert "colour" in str(exc)
    else:
        raise AssertionError("an unknown field silently matched nothing")


def test_the_state_directory_is_gitignored_once(tmp_path: Path) -> None:
    ensure_git_rules(tmp_path)
    ensure_git_rules(tmp_path)
    rules = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert rules.count(".chock/state/") == 1


def test_the_helper_is_vendored_byte_for_byte_while_a_script_gate_needs_it(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, tool_call_gate(script=True), script=SCRIPT)
    install_hooks(repo, "claude_code")
    vendored = repo / ".chock" / "bin" / "chock_session.py"
    assert vendored.read_bytes() == Path(session_reader.__file__).read_bytes()
    for gate in (repo / ".chock" / "compiled").glob("*/*/tool-call-gate.json"):
        gate.write_text(json.dumps({"kind": "content_regex"}), encoding="utf-8")
    sync_session_helper(repo)
    assert not vendored.exists()


def test_no_helper_without_a_script_gate(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, tool_call_gate())
    install_hooks(repo, "claude_code")
    assert not (repo / ".chock" / "bin" / "chock_session.py").exists()

"""`chock status --only log --by ...`: a week of gate events turned into a per-group report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from findings_support import gate_spec, judge_write, make_gate, repo_with

from chock import lifecycle
from chock.gate.runner import GATE_LOG_ENV
from chock.gatelog import group_events, main, read_events

SQL = "SQL"
TRAVERSAL = "path traversal"


def event(day: int, verdict: str, **extra: object) -> dict:
    return {
        "ts": f"2026-09-{day:02d}T09:00:00Z",
        "policy_id": "java-security",
        "surface": "pre-tool-use",
        "event": "tool_use",
        "kind": "script",
        "verdict": verdict,
        "match_count": 0,
        "matches": [],
        **extra,
    }


def finding(rule: str, path: str, *, verdict: str = "warn", day: int = 1, agent: str | None = None, **extra) -> dict:
    record = event(
        day,
        verdict,
        rules={rule: 1},
        matches=[f"{path}:7: SECRET-LOOKING-MESSAGE"],
        new_findings=1,
        baseline_findings=2,
        **extra,
    )
    if agent:
        record["agent"] = agent
    return record


def week() -> list[dict]:
    """java-security: 14 would-block findings (9 traversal, 5 sql) from 3 agents, plus other traffic."""
    agents = ["CLAUDECODE=1", "AI_AGENT", "CURSOR_AGENT"]
    records = [
        finding(TRAVERSAL, "src/Files.java", day=1 + i % 7, agent=agents[i % 3], would_block=True) for i in range(9)
    ]
    records += [finding(SQL, "src/Repo.java", day=1 + i % 7, agent=agents[i % 3], would_block=True) for i in range(5)]
    records += [
        finding(SQL, "src/Repo.java", verdict="block", day=3, agent="CLAUDECODE=1"),
        event(4, "ask", event="commit", surface="git-hook"),
        event(5, "allow"),
        {**event(6, "warn"), "policy_id": "scan-secrets", "matches": ["config/app.env: content pattern"]},
    ]
    return records


def write_log(repo: Path, records: list[dict]) -> None:
    path = repo / ".chock" / "log" / "gate-events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def by(records: list[dict], key: str) -> dict[str, dict]:
    return {row["group"]: row for row in group_events(records, key)}


def test_by_policy_counts_verdicts_findings_agents_rules_and_files() -> None:
    row = by(week(), "policy")["java-security"]

    assert (row["block"], row["ask"], row["warn"], row["would_block"]) == (1, 1, 14, 14)
    assert (row["events"], row["allow"]) == (17, 1)
    assert (row["new_findings"], row["baseline_findings"]) == (15, 30)
    assert row["agents"] == ["AI_AGENT", "CLAUDECODE=1", "CURSOR_AGENT"]
    assert row["rules"] == {TRAVERSAL: 9, SQL: 6}
    assert row["files"] == [{"path": "src/Files.java", "count": 9}, {"path": "src/Repo.java", "count": 6}]


def test_by_rule_groups_each_rule_and_leaves_unkeyed_events_unknown() -> None:
    groups = by(week(), "rule")

    assert groups[TRAVERSAL]["warn"] == 9
    assert groups[SQL]["block"] == 1
    assert groups["unknown"]["events"] == 3
    assert groups[SQL]["rules"] == {}


def test_by_agent_and_by_event() -> None:
    agents = by(week(), "agent")
    events = by(week(), "event")

    assert agents["CLAUDECODE=1"]["events"] == 6
    assert agents["unknown"]["events"] == 3
    assert events["commit"]["ask"] == 1
    assert events["tool_use"]["events"] == 17


def test_old_records_without_the_new_fields_group_under_unknown() -> None:
    old = [{"ts": "2026-08-01T00:00:00Z", "policy_id": "scan-secrets", "surface": "git-hook", "verdict": "block"}]

    assert list(by(old, "agent")) == ["unknown"]
    assert list(by(old, "rule")) == ["unknown"]
    assert list(by(old, "event")) == ["unknown"]
    row = by(old, "policy")["scan-secrets"]
    assert (row["block"], row["would_block"], row["agents"], row["files"]) == (1, 0, [], [])


def test_only_a_leading_path_is_read_from_matches() -> None:
    record = event(1, "block", matches=["a.py:3: content pattern", "assertions removed across tests: 3", "main", 5])

    assert [f["path"] for f in by([record], "policy")["java-security"]["files"]] == ["a.py"]


def test_top_files_are_capped() -> None:
    record = event(1, "block", matches=[f"f{i}.py: content pattern" for i in range(6)])

    assert len(by([record], "policy")["java-security"]["files"]) == 3


def test_text_table_and_headline(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    write_log(tmp_path, week())

    assert main(["--repo", str(tmp_path), "--by", "policy"]) == 0

    out = capsys.readouterr().out
    assert out.splitlines()[0].split() == [
        "policy",
        "events",
        "blocked",
        "asked",
        "warned",
        "would-block",
        "new",
        "baseline",
    ]
    assert "java-security: 1 blocked, 1 asked, 14 warned, 14 would-block (9 path traversal" in out
    assert "across 3 agents" in out
    assert "SECRET-LOOKING-MESSAGE" not in out


def test_would_block_column_is_absent_until_a_record_carries_it(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    write_log(tmp_path, [event(1, "block")])

    assert main(["--repo", str(tmp_path), "--by", "policy"]) == 0

    assert "would-block" not in capsys.readouterr().out


def test_markdown_summary(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    write_log(tmp_path, week())

    assert main(["--repo", str(tmp_path), "--format", "md", "--since", "100000"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "### Chock gate log by policy (last 100000 days)"
    assert lines[2].startswith("| policy | events | blocked | asked | warned | would-block |")
    assert lines[3] == "|---|---|---|---|---|---|---|---|"
    assert lines[4].startswith("| java-security | 17 | 1 | 1 | 14 | 14 | 15 | 30 |")
    assert any(line.startswith("- java-security: 1 blocked") for line in lines)
    assert not any("SECRET-LOOKING-MESSAGE" in line for line in lines)


def test_markdown_cells_cannot_break_out_of_the_table(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    write_log(tmp_path, [event(1, "block", agent="a|b`c\n<x>")])

    assert main(["--repo", str(tmp_path), "--format", "md", "--by", "agent"]) == 0

    row = capsys.readouterr().out.splitlines()[4]
    assert row.startswith("| a\\|b'c &lt;x> |")


def test_empty_log_markdown(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert main(["--repo", str(tmp_path), "--format", "md"]) == 0

    assert capsys.readouterr().out.endswith("No gate outcomes recorded yet.\n")


def test_json_groups(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    write_log(tmp_path, week())

    assert main(["--repo", str(tmp_path), "--by", "rule", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["by"] == "rule"
    assert payload["events"] == len(week())
    assert {g["group"] for g in payload["groups"]} == {TRAVERSAL, SQL, "unknown"}
    assert payload["groups"][0]["files"][0]["path"].endswith(".java")


def test_json_without_by_keeps_its_shape(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    write_log(tmp_path, week())

    assert main(["--repo", str(tmp_path), "--json"]) == 0

    assert set(json.loads(capsys.readouterr().out)) == {"summary", "silent", "events"}


def test_json_and_markdown_are_exclusive(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["--repo", str(tmp_path), "--json", "--format", "md"])

    assert stopped.value.code == 2


def test_policy_filter_applies_to_groups(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    write_log(tmp_path, week())

    assert main(["--repo", str(tmp_path), "--policy", "scan-secrets", "--by", "policy", "--json"]) == 0

    assert [g["group"] for g in json.loads(capsys.readouterr().out)["groups"]] == ["scan-secrets"]


def test_chock_status_forwards_the_log_flags(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    write_log(tmp_path, week())

    assert lifecycle.status_main(["--repo", str(tmp_path), "--only", "log", "--by", "agent", "--json"]) == 0

    assert json.loads(capsys.readouterr().out)["by"] == "agent"


def test_chock_status_refuses_log_flags_without_the_log_section(tmp_path: Path) -> None:
    assert lifecycle.status_main(["--repo", str(tmp_path), "--by", "agent"]) == 2


def compiled_gate(repo: Path) -> Path:
    """The toy gate at the compiled path shape, which is where the runner logs from."""
    make_gate(repo)
    gate = repo / ".chock" / "compiled" / "java-security" / "pre-tool-use" / "gate.json"
    gate.parent.mkdir(parents=True)
    gate.write_text(json.dumps(gate_spec()), encoding="utf-8")
    return gate


def recorded(repo: Path) -> dict:
    lines = (repo / ".chock" / "log" / "gate-events.jsonl").read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])


def test_runner_records_rule_ids_and_the_agent_signal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(GATE_LOG_ENV, raising=False)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("TOY_EXIT", "4")
    repo = repo_with(tmp_path, **{"app.py": "x = BAD\n"})

    assert judge_write(compiled_gate(repo), repo, "x = BAD\ny = BAD two\n") == 4

    record = recorded(repo)
    assert record["agent"] == "CLAUDECODE=1"
    assert record["verdict"] == "warn"
    assert record["rules"] == {"bad": 1}
    assert "BAD" not in json.dumps(record["rules"])
    assert read_events(repo)[-1]["agent"] == "CLAUDECODE=1"


def test_runner_leaves_agent_out_for_a_person(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(GATE_LOG_ENV, raising=False)
    repo = repo_with(tmp_path, **{"app.py": "x = 1\n"})

    judge_write(compiled_gate(repo), repo, "x = BAD\n")

    record = recorded(repo)
    assert "agent" not in record
    assert record["verdict"] == "block"


def test_a_malformed_rule_is_not_logged_and_does_not_change_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(GATE_LOG_ENV, raising=False)
    monkeypatch.setenv("TOY_EXIT", "4")
    monkeypatch.setenv("TOY_RULE", "query(sql + id)")
    repo = repo_with(tmp_path, **{"app.py": "x = 1\n"})

    assert judge_write(compiled_gate(repo), repo, "y = BAD two\n") == 4

    record = recorded(repo)
    assert "rules" not in record
    assert record["new_findings"] == 1


def test_chock_status_markdown_is_only_the_summary(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    write_log(tmp_path, week())

    assert lifecycle.status_main(["--repo", str(tmp_path), "--only", "log", "--format", "md"]) == 0

    assert capsys.readouterr().out.startswith("### Chock gate log by policy")

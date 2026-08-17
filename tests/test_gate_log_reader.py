"""`chock status --only log`: turning the outcome JSONL into an answer.

The reader exists so the log is not write-only. Its most valuable output is the part that
is *absent* from the log -- a policy with no recorded event has never been consulted, which
reads as "fine" everywhere else in the tooling.
"""

from __future__ import annotations

import json
from pathlib import Path

from chock.gatelog import installed_policies, main, read_events, summarize

RECORDS = [
    {"ts": "2026-08-01T00:00:00Z", "policy_id": "scan-secrets", "surface": "git-hook", "verdict": "allow"},
    {"ts": "2026-08-02T00:00:00Z", "policy_id": "scan-secrets", "surface": "git-hook", "verdict": "block"},
    {"ts": "2026-08-03T00:00:00Z", "policy_id": "scan-secrets", "surface": "git-hook", "verdict": "allow"},
    {"ts": "2026-08-04T00:00:00Z", "policy_id": "protect-main-branch", "surface": "git-hook", "verdict": "allow"},
]


def write_log(repo: Path, records: list[dict], name: str = "gate-events.jsonl") -> Path:
    path = repo / ".chock" / "log" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def test_summary_counts_by_policy_and_surface(tmp_path: Path) -> None:
    write_log(tmp_path, RECORDS)

    summary = summarize(read_events(tmp_path))

    assert [e["policy_id"] for e in summary] == ["scan-secrets", "protect-main-branch"]
    top = summary[0]
    assert (top["events"], top["allow"], top["block"]) == (3, 2, 1)
    assert top["last_block"] == "2026-08-02T00:00:00Z"
    assert summary[1]["last_block"] is None


def test_rotated_log_is_included_oldest_first(tmp_path: Path) -> None:
    write_log(tmp_path, RECORDS[:2], name="gate-events.1.jsonl")
    write_log(tmp_path, RECORDS[2:])

    events = read_events(tmp_path)

    assert len(events) == 4
    assert [e["ts"] for e in events] == sorted(e["ts"] for e in events)


def test_torn_and_foreign_lines_are_skipped_not_fatal(tmp_path: Path) -> None:
    """Hooks append concurrently. A half-written line loses a record, not the report."""
    path = write_log(tmp_path, RECORDS)
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"ts": "2026-08-05T00:00:00Z", "policy_id": "scan-sec\n')  # torn
        fh.write("\n")
        fh.write('{"note": "no policy_id"}\n')

    assert len(read_events(tmp_path)) == 4


def test_since_filters_by_age(tmp_path: Path) -> None:
    write_log(tmp_path, RECORDS)

    assert read_events(tmp_path, since_days=1) == []
    assert len(read_events(tmp_path, since_days=100_000)) == 4


def test_missing_log_reports_nothing_rather_than_failing(tmp_path: Path, capsys) -> None:
    assert main(["--repo", str(tmp_path)]) == 0
    assert "No gate outcomes recorded yet." in capsys.readouterr().out


def test_silent_policies_are_named(tmp_path: Path, capsys) -> None:
    """The finding nobody asks for: installed, compiled, and never once consulted."""
    for policy_id in ("scan-secrets", "protect-main-branch", "git-safety"):
        manifest = tmp_path / ".agents" / "policies" / policy_id / "manifest.yaml"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(f"id: {policy_id}\n", encoding="utf-8")
    write_log(tmp_path, RECORDS)

    assert main(["--repo", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "Never recorded (1): git-safety" in out
    assert "scan-secrets" in out


def test_nested_baseline_policies_are_discovered(tmp_path: Path) -> None:
    """`init` installs packs at .agents/policies/_baseline/<id>/, one level deeper."""
    nested = tmp_path / ".agents" / "policies" / "_baseline" / "scan-secrets" / "manifest.yaml"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text("id: scan-secrets\n", encoding="utf-8")

    assert installed_policies(tmp_path) == ["scan-secrets"]


def test_policy_filter_restricts_both_sections(tmp_path: Path, capsys) -> None:
    write_log(tmp_path, RECORDS)

    assert main(["--repo", str(tmp_path), "--policy", "scan-secrets", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["events"] == 3
    assert [e["policy_id"] for e in payload["summary"]] == ["scan-secrets"]
    assert payload["silent"] == []


def test_json_output_is_machine_readable(tmp_path: Path, capsys) -> None:
    write_log(tmp_path, RECORDS)

    assert main(["--repo", str(tmp_path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["events"] == 4
    assert {"summary", "silent", "events"} == set(payload)

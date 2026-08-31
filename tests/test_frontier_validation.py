"""Frontier validation modes: `chock check --only validate --mode frontier-<agent>`."""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from chock.validation import frontier
from chock.validation.report import Report

STANDARD = {
    "skill_name": {"pattern": "^[a-z0-9]+(-[a-z0-9]+)*$"},
    "skill_description": {"max_length": 40},
    "skill_md_body": {"max_lines": 3},
    "compatibility": {"max_length": 10},
}


@pytest.fixture
def standards(tmp_path: Path, monkeypatch):
    """Write a standard file the loader will find, with a controllable fetched_at."""

    def _write(agent_file: str, data: dict, fetched_days_ago: int | None = 0) -> Path:
        root = tmp_path / "standards"
        root.mkdir(exist_ok=True)
        payload = dict(data)
        if fetched_days_ago is not None:
            when = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=fetched_days_ago)
            payload["fetched_at"] = when.isoformat()
        path = root / f"{agent_file}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(frontier, "STANDARDS_DIR", root)
        return path

    return _write


def _checks(report: Report) -> list[str]:
    return [f.check for f in report.errors + report.warnings + report.infos]


def test_missing_standard_warns_with_the_command_that_fixes_it(tmp_path: Path, standards) -> None:
    """An absent standard is not a validation failure -- the adopter simply has not ingested one."""
    standards("agentskills", STANDARD)
    report = Report()
    frontier.check_frontier_mode(tmp_path, {"id": "x"}, "skill", "frontier-nosuchagent", report)

    assert _checks(report) == ["frontier"]
    assert report.errors == [], "an un-ingested standard is not the artifact's fault"
    assert "frontier_ingest --agent nosuchagent" in report.warnings[0].message


def test_a_conformant_skill_produces_no_findings(tmp_path: Path, standards) -> None:
    standards("claude-code", STANDARD)
    (tmp_path / "SKILL.md").write_text("one" + chr(10) + "two" + chr(10), encoding="utf-8")
    manifest = {"id": "well-named", "description": "short enough", "compatibility": "all"}

    report = Report()
    frontier.check_frontier_mode(tmp_path, manifest, "skill", "frontier-claude", report)
    assert _checks(report) == []


def test_each_limit_is_reported_against_the_standard_not_a_constant(tmp_path: Path, standards) -> None:
    """Every limit comes from the pinned standard, so the message must quote that number."""
    standards("claude-code", STANDARD)
    (tmp_path / "SKILL.md").write_text((chr(10)).join(["l"] * 9), encoding="utf-8")
    manifest = {
        "id": "Bad_Name",
        "description": "x" * 41,
        "compatibility": "y" * 11,
    }

    report = Report()
    frontier.check_frontier_mode(tmp_path, manifest, "skill", "frontier-claude", report)
    codes = set(_checks(report))

    assert {"frontier_description", "frontier_body", "frontier_name"} <= codes
    assert {f.check for f in report.errors} == codes - {"frontier_staleness"}, "limits are errors"
    text = " ".join(f.message for f in report.errors)
    assert "40 chars" in text and "3 lines" in text


def test_a_stale_standard_warns_without_failing_validation(tmp_path: Path, standards) -> None:
    """Staleness is advisory: an old standard is a reason to re-ingest, not to fail a build."""
    standards("claude-code", STANDARD, fetched_days_ago=200)
    manifest = {"id": "fine", "description": "ok"}

    report = Report()
    frontier.check_frontier_mode(tmp_path, manifest, "skill", "frontier-claude", report)
    staleness = [f for f in report.warnings if f.check == "frontier_staleness"]
    assert len(staleness) == 1, "staleness is a warning, never an error"
    assert report.errors == []
    assert "200 days ago" in staleness[0].message


def test_a_malformed_timestamp_does_not_fail_validation(tmp_path: Path, standards) -> None:
    """A broken `fetched_at` is a defect in the standard file, not in the artifact being checked."""
    standards("claude-code", dict(STANDARD, fetched_at="not-a-date"), fetched_days_ago=None)
    report = Report()
    frontier.check_frontier_mode(tmp_path, {"id": "fine", "description": "ok"}, "skill", "frontier-claude", report)
    assert "frontier_staleness" not in _checks(report)


def test_non_skill_artifacts_skip_the_skill_limits(tmp_path: Path, standards) -> None:
    """The limits describe skills. A hook with a long description is not a frontier violation."""
    standards("claude-code", STANDARD)
    manifest = {"id": "a-hook", "description": "x" * 200}

    report = Report()
    frontier.check_frontier_mode(tmp_path, manifest, "hook", "frontier-claude", report)
    assert "frontier_description" not in _checks(report)

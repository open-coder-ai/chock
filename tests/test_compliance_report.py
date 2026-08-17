"""Step 4: chock compliance report."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from chock.authoring import compliance


def _make_policy(tmp_path: Path, policy_id: str, compliance_data: object) -> Path:
    pack = tmp_path / ".agents" / "policies" / policy_id
    pack.mkdir(parents=True)
    manifest = {
        "id": policy_id,
        "name": policy_id,
        "version": "0.1.0",
        "description": "A policy.",
        "enforcement": "advise",
        "artifact": "rule",
        "rule": {"text": f"rule for {policy_id}"},
        "provenance": {
            "author": "a",
            "source_repo": "https://example.com",
            "license": "Apache-2.0",
            "trust_tier": "community",
        },
        "lifecycle": {"status": "draft"},
    }
    if compliance_data is not None:
        manifest["compliance"] = compliance_data
    (pack / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return pack


def test_bare_string_claim_renders_partial_not_covered(tmp_path: Path) -> None:
    _make_policy(tmp_path, "p1", {"owasp_asi": ["ASI02"]})
    report = compliance._build_report(tmp_path, "owasp_asi")
    assert report["owasp_asi"]["ASI02"]["state"] == "partial"
    assert report["owasp_asi"]["ASI02"]["policies"] == [{"id": "p1", "coverage": "partial", "note": ""}]


def test_explicit_full_renders_covered(tmp_path: Path) -> None:
    _make_policy(
        tmp_path,
        "p1",
        {
            "owasp_asi": [
                {
                    "control": "ASI02",
                    "coverage": "full",
                    "note": "blocks destructive commands",
                }
            ]
        },
    )
    report = compliance._build_report(tmp_path, "owasp_asi")
    assert report["owasp_asi"]["ASI02"]["state"] == "covered"
    assert report["owasp_asi"]["ASI02"]["policies"] == [
        {"id": "p1", "coverage": "full", "note": "blocks destructive commands"}
    ]


def test_mixed_claims_renders_covered(tmp_path: Path) -> None:
    _make_policy(tmp_path, "p1", {"owasp_asi": ["ASI02"]})
    _make_policy(
        tmp_path,
        "p2",
        {
            "owasp_asi": [
                {
                    "control": "ASI02",
                    "coverage": "full",
                    "note": "full protection",
                }
            ]
        },
    )
    report = compliance._build_report(tmp_path, "owasp_asi")
    assert report["owasp_asi"]["ASI02"]["state"] == "covered"


def test_other_controls_uncovered(tmp_path: Path) -> None:
    _make_policy(
        tmp_path,
        "p1",
        {
            "owasp_asi": [
                {
                    "control": "ASI02",
                    "coverage": "full",
                    "note": "",
                }
            ]
        },
    )
    report = compliance._build_report(tmp_path, "owasp_asi")
    for control in ("ASI01", "ASI03", "ASI04", "ASI05", "ASI06", "ASI07", "ASI08", "ASI09", "ASI10"):
        assert report["owasp_asi"][control]["state"] == "uncovered"
        assert report["owasp_asi"][control]["policies"] == []


def test_json_shape_is_stable(tmp_path: Path) -> None:
    _make_policy(tmp_path, "p1", {"owasp_asi": ["ASI05"]})
    result = subprocess.run(
        [sys.executable, "-m", "chock.cli", "compliance", "report", "--repo", str(tmp_path), "--json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "owasp_asi" in data
    entry = data["owasp_asi"]["ASI05"]
    assert entry["state"] == "partial"
    assert entry["policies"] == [{"id": "p1", "coverage": "partial", "note": ""}]
    for control in ("ASI01", "ASI02", "ASI03", "ASI04", "ASI06", "ASI07", "ASI08", "ASI09", "ASI10"):
        assert data["owasp_asi"][control]["state"] == "uncovered"


def test_zero_compliance_blocks_reports_all_uncovered(tmp_path: Path) -> None:
    _make_policy(tmp_path, "p1", None)
    report = compliance._build_report(tmp_path, "owasp_asi")
    for control in report["owasp_asi"]:
        assert report["owasp_asi"][control]["state"] == "uncovered"
        assert report["owasp_asi"][control]["policies"] == []


def test_cli_table_prints_partial_for_bare_string(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_policy(tmp_path, "p1", {"owasp_asi": ["ASI02"]})
    assert compliance.main(["report", "--repo", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert "ASI02" in captured.out
    assert "partial" in captured.out
    assert "p1" in captured.out


def test_disabled_policy_does_not_claim_coverage(tmp_path: Path) -> None:
    """A policy the adopter turned off enforces nothing, so it must not claim coverage.

    Reporting a control as covered by a disabled policy is false assurance -- the same
    class of error as treating a bare string claim as `full`.
    """
    _make_policy(tmp_path, "p1", {"owasp_asi": [{"control": "ASI04", "coverage": "full", "note": "n"}]})
    (tmp_path / ".chock").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".chock" / "config.yaml").write_text("policies:\n  disabled: [p1]\n  overrides: {}\n", encoding="utf-8")

    report = compliance._build_report(tmp_path, "owasp_asi")
    assert report["owasp_asi"]["ASI04"]["state"] == "uncovered"
    assert report["owasp_asi"]["ASI04"]["policies"] == []


def test_enabled_policy_still_claims_coverage(tmp_path: Path) -> None:
    """Control case: the same policy left enabled must still be reported."""
    _make_policy(tmp_path, "p1", {"owasp_asi": [{"control": "ASI04", "coverage": "full", "note": "n"}]})
    (tmp_path / ".chock").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".chock" / "config.yaml").write_text("policies:\n  disabled: []\n  overrides: {}\n", encoding="utf-8")

    report = compliance._build_report(tmp_path, "owasp_asi")
    assert report["owasp_asi"]["ASI04"]["state"] == "covered"

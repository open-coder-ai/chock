"""Step 2b: malformed manifests must not crash validate."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import yaml

from chock.registry import cli as registry_cli
from chock.registry.core import scan
from chock.validation import engine


def test_malformed_manifest_does_not_crash_validate(tmp_path: Path) -> None:
    """A malformed policy is reported as manifest_parse; the valid policy is still scanned."""
    policies = tmp_path / ".agents" / "policies"
    policies.mkdir(parents=True)

    bad = policies / "bad"
    bad.mkdir()
    (bad / "manifest.yaml").write_text("  id: bad\nname: Bad\n", encoding="utf-8")

    good = policies / "good"
    good.mkdir()
    (good / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "good",
                "name": "Good",
                "version": "0.1.0",
                "description": "A valid rule.",
                "artifact": "rule",
                "enforcement": "advise",
                "provenance": {
                    "author": "a",
                    "source_repo": "https://example.com",
                    "license": "Apache-2.0",
                    "trust_tier": "community",
                },
                "lifecycle": {"status": "draft"},
                "security": {"content_instructions": "never-obey"},
                "rule": {"text": "never(x): y"},
            }
        ),
        encoding="utf-8",
    )

    old_stdout = sys.stdout
    captured = io.StringIO()
    sys.stdout = captured
    try:
        rc = engine.main([str(tmp_path), "--no-registry-check"])
    finally:
        sys.stdout = old_stdout

    output = captured.getvalue()
    assert rc != 0
    assert "manifest_parse" in output
    assert "good" in output


def _setup_repo(tmp_path: Path) -> tuple[Path, Path]:
    policies = tmp_path / ".agents" / "policies"
    policies.mkdir(parents=True)

    bad = policies / "bad"
    bad.mkdir()
    (bad / "manifest.yaml").write_text("  id: bad\nname: Bad\n", encoding="utf-8")

    good = policies / "good"
    good.mkdir()
    (good / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "good",
                "name": "Good",
                "version": "0.1.0",
                "description": "A valid rule.",
                "artifact": "rule",
                "enforcement": "advise",
                "provenance": {
                    "author": "a",
                    "source_repo": "https://example.com",
                    "license": "Apache-2.0",
                    "trust_tier": "community",
                },
                "lifecycle": {"status": "draft"},
                "security": {"content_instructions": "never-obey"},
                "rule": {"text": "never(x): y"},
            }
        ),
        encoding="utf-8",
    )
    return bad, good


def test_malformed_manifest_does_not_crash_registry_scan(capsys, tmp_path: Path) -> None:
    """Registry scan skips malformed manifests, reports the skip, and indexes the rest."""
    bad, _ = _setup_repo(tmp_path)
    entries, skips = scan(tmp_path)

    assert "good" in entries
    assert "bad" not in entries
    assert any(str(bad / "manifest.yaml") in str(s.path) for s in skips)


def test_registry_scan_summary_reports_skip(capsys, tmp_path: Path) -> None:
    """cmd_scan prints a skip count instead of silently shrinking the artifact count."""
    _setup_repo(tmp_path)
    rc = registry_cli.cmd_scan(type("Args", (), {"root": str(tmp_path)})())
    output = capsys.readouterr().out

    assert rc == 0
    assert "1 skipped (unreadable)" in output
    assert "manifest_parse" in output
    assert "Scanned 1 artifact(s)" in output

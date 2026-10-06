"""SEC-5: a sandbox-tier rule passes validation without claiming review, through the escape its own error names."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from chock.validation import engine
from chock.validation.loading import get_validator

VALIDATOR = get_validator("manifest.schema.json")
REASON = "authored by the installing user"


def _rule(**extra: object) -> dict:
    return {
        "id": "my-rule",
        "name": "My Rule",
        "version": "0.1.0",
        "description": "A person's own rule.",
        "artifact": "rule",
        "enforcement": "advise",
        "rule": {"text": "never(run): terraform destroy"},
        "provenance": {"author": "me", "source_repo": "local", "license": "proprietary", "trust_tier": "sandbox"},
        "lifecycle": {"status": "draft"},
        "security": {"content_instructions": "never-obey"},
        **extra,
    }


def _errors(manifest: dict) -> list[str]:
    return [e.message for e in VALIDATOR.iter_errors(manifest)]


def test_the_schema_accepts_the_override_with_its_reason() -> None:
    assert _errors(_rule(ambient_override=True, ambient_override_reason=REASON)) == []


def test_the_override_without_a_reason_is_refused_by_the_schema() -> None:
    assert any("'ambient_override_reason' is a required property" in e for e in _errors(_rule(ambient_override=True)))


@pytest.mark.parametrize("reason", ["", "x" * 501])
def test_an_empty_or_long_reason_is_refused(reason: str) -> None:
    assert _errors(_rule(ambient_override=True, ambient_override_reason=reason))


def _validate(tmp_path: Path, manifest: dict, capsys) -> tuple[int, str]:
    folder = tmp_path / ".agents" / "policies" / "my-rule"
    (folder / "evals").mkdir(parents=True)
    (folder / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    suite = {
        "suite": {
            "id": "my-rule-tests-v1",
            "policy_id": "my-rule",
            "version_constraint": ">=0.1.0",
            "maintainer": "me",
            "primary_metric": "pass_rate",
            "metrics": {"pass_rate": {"direction": "higher_is_better", "threshold": 1.0}},
            "cases": [
                {"id": f"tc-00{n}", "category": c, "prompt": "Tear down the stack.", "expect": "The agent refuses."}
                for n, c in enumerate(("trigger", "negative_trigger", "behavior"), start=1)
            ],
        }
    }
    (folder / "evals" / "suite.yaml").write_text(yaml.safe_dump(suite, sort_keys=False), encoding="utf-8")
    capsys.readouterr()
    code = engine.main([str(tmp_path)])
    return code, capsys.readouterr().out


def test_a_sandbox_rule_without_the_override_fails_sec5(tmp_path: Path, capsys) -> None:
    code, out = _validate(tmp_path, _rule(), capsys)
    assert code != 0
    assert "ambient_tier: Rule is wired into ambient context (SEC-5)" in out
    assert "ambient_override: true with ambient_override_reason" in out


def test_the_remedy_the_error_suggests_passes_without_claiming_review(tmp_path: Path, capsys) -> None:
    code, out = _validate(tmp_path, _rule(ambient_override=True, ambient_override_reason=REASON), capsys)
    assert code == 0, out
    assert "ambient_tier" not in out
    assert "schema:" not in out

"""`chock review require`: command_set_hash (H1) and the five ordered judgements."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from chock.review.evidence import build, command_set_hash, require, required_checks, verify

SCRIPT_ALWAYS_FAILS = ["python", "-c", "import sys; sys.exit(1)"]


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with a base commit on `main` and one change on a branch."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--quiet", ".")
    _git(root, "config", "user.email", "a@b.c")
    _git(root, "config", "user.name", "t")
    _git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "feat/x")
    (root / "feature.txt").write_text("change\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "change")
    return root


@pytest.fixture
def evidence(repo: Path) -> dict:
    return build(repo, "main", {"kind": "agent", "id": "test"}, ["validate"])


def _write_config(repo: Path, review: dict) -> None:
    config = repo / ".chock" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(yaml.safe_dump({"chock": {"review": review}}), encoding="utf-8")


def _write_evidence(repo: Path, evidence: dict, name: str = "e.json") -> Path:
    dest = repo / ".chock" / "evidence" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(evidence), encoding="utf-8")
    return dest


def _touch_workflow(repo: Path) -> None:
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "touch workflow")


def test_command_set_hash_changes_when_a_required_checks_command_is_redefined(repo: Path) -> None:
    """H1, by hash rather than lookup: a redefined registry entry must not wave through."""
    _write_config(repo, {"required_checks": ["effects-honesty"], "checks": {"effects-honesty": ["check"]}})
    before = command_set_hash(repo)

    _write_config(repo, {"required_checks": ["effects-honesty"], "checks": {"effects-honesty": ["check", "--strict"]}})
    after = command_set_hash(repo)

    assert before != after


def test_command_set_hash_is_over_the_empty_set_when_no_required_checks_are_declared(repo: Path) -> None:
    import hashlib

    assert required_checks(repo) == []
    assert command_set_hash(repo) == hashlib.sha256(b"{}").hexdigest()


def test_require_rejects_when_no_evidence_matches_the_diff(repo: Path) -> None:
    failures = require(repo, "main")
    assert any("no evidence matches this diff" in f for f in failures), failures
    assert any("chock review emit" in f for f in failures), failures


def test_require_passes_honest_evidence_with_no_required_set(repo: Path, evidence: dict) -> None:
    _write_evidence(repo, evidence)
    assert require(repo, "main") == []


def test_require_forwards_verify_failures_as_the_valid_judgement(repo: Path, evidence: dict) -> None:
    tampered = dict(evidence)
    tampered["unattestable"] = []
    _write_evidence(repo, tampered)

    failures = require(repo, "main")

    assert any("unattestable paths disagree" in f for f in failures), failures


def test_require_rejects_a_stale_command_set_hash_even_when_every_named_check_passes(
    repo: Path, evidence: dict
) -> None:
    """Acceptance #2: a hash computed over a different required set is rejected regardless of outcome."""
    _write_config(repo, {"required_checks": ["validate"]})
    assert verify(repo, evidence, "main") == [], "the named check is present and verify() still holds"

    forged = dict(evidence, command_set_hash="0" * 64)
    _write_evidence(repo, forged)

    failures = require(repo, "main")
    assert any("command_set_hash" in f for f in failures), failures


def test_require_rejects_a_failing_required_check_while_verify_still_exits_clean(repo: Path) -> None:
    """Acceptance #3 (H2): validity and outcome are judged separately."""
    _write_config(repo, {"checks": {"always-fails": SCRIPT_ALWAYS_FAILS}, "required_checks": ["always-fails"]})
    failing = build(repo, "main", {"kind": "agent", "id": "test"}, ["always-fails"])
    _write_evidence(repo, failing)

    assert verify(repo, failing, "main") == [], "a record of failure is still valid evidence"
    failures = require(repo, "main")
    assert any("required check(s) recorded failing" in f for f in failures), failures
    assert any("always-fails" in f for f in failures), failures


def test_require_rejects_an_unattested_change_to_an_unattestable_path_under_the_floor(repo: Path) -> None:
    """Acceptance #4: a diff touching .github/workflows/ with zero attestations fails at floor 1."""
    _write_config(repo, {"attestation_floor": 1})
    _touch_workflow(repo)

    fresh = build(repo, "main", {"kind": "agent", "id": "test"}, ["validate"])
    _write_evidence(repo, fresh)

    failures = require(repo, "main")
    assert any(".github/workflows/" in f for f in failures), failures
    assert any("attestation" in f for f in failures), failures


def test_require_passes_once_the_attestation_floor_is_met(repo: Path) -> None:
    _write_config(repo, {"attestation_floor": 1})
    _touch_workflow(repo)

    fresh = build(repo, "main", {"kind": "agent", "id": "test"}, ["validate"])
    fresh["attested"] = [{"criterion": "ci-safety", "claim": "workflow reviewed", "basis": "read it in full"}]
    _write_evidence(repo, fresh)

    assert require(repo, "main") == []

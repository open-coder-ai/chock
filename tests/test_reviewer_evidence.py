"""Reviewer evidence: what it refuses, and the one thing it deliberately does not check."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from chock.review.evidence import (
    DEFAULT_UNATTESTABLE,
    EMPTY_DIFF_SHA,
    SCHEMA_URL,
    EvidenceError,
    build,
    check_registry,
    diff_sha,
    unattestable_paths,
    verify,
)

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "chock" / "validation" / "schemas" / "reviewer-evidence-v1.json"
)


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


def test_diff_sha_does_not_depend_on_the_platform_locale(repo: Path, monkeypatch) -> None:
    """A cp1252 machine and a UTF-8 machine must name the same diff."""
    import hashlib

    (repo / "feature.txt").write_text("an em dash — and a middot ·\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "non-ascii")

    base = subprocess.run(
        ["git", "merge-base", "main", "HEAD"], cwd=repo, capture_output=True, encoding="utf-8"
    ).stdout.strip()
    raw = subprocess.run(
        ["git", "diff", "--no-color", f"{base}...HEAD", "--", ".", ":(exclude).chock/evidence/*"],
        cwd=repo,
        capture_output=True,
    ).stdout
    expected = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()

    assert diff_sha(repo, "main") == expected


def test_emitted_evidence_conforms_to_the_published_schema(evidence: dict) -> None:
    Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))).validate(evidence)
    assert evidence["$schema"] == SCHEMA_URL


def test_honest_evidence_holds(repo: Path, evidence: dict) -> None:
    assert verify(repo, evidence, "main") == []


def test_a_forged_result_is_caught_by_re_running(repo: Path, evidence: dict) -> None:
    """The central claim: a `verified` entry is worth what the re-run says, not what it says."""
    evidence["verified"][0]["result"] = "fail"

    failures = verify(repo, evidence, "main")

    assert any("claims fail, re-running gives pass" in f for f in failures)


def test_the_recorded_command_is_never_executed(repo: Path, evidence: dict, tmp_path: Path) -> None:
    """Evidence is contributor-authored. Running its `command` would be RCE in CI."""
    canary = tmp_path / "PWNED"
    evidence["verified"][0]["command"] = f"chock check; touch {canary}"

    failures = verify(repo, evidence, "main")

    assert not canary.exists(), "the verifier executed a command supplied by the evidence"
    assert any("registry runs" in f for f in failures)


def test_an_unknown_check_fails_rather_than_being_skipped(repo: Path, evidence: dict) -> None:
    """Otherwise `security-reviewed: pass` is a tick nobody can contradict."""
    evidence["verified"].append({"check": "security-reviewed", "result": "pass"})

    assert any("not a known check" in f for f in verify(repo, evidence, "main"))


def test_unattestable_paths_come_from_the_repo_not_the_evidence(repo: Path, evidence: dict) -> None:
    """A submitter who can shorten this list can self-certify the checking machinery."""
    evidence["unattestable"] = []

    assert any("unattestable paths disagree" in f for f in verify(repo, evidence, "main"))


def test_config_can_widen_unattestable_but_evidence_cannot(repo: Path) -> None:
    config = repo / ".chock"
    config.mkdir(exist_ok=True)
    (config / "config.yaml").write_text(
        yaml.safe_dump({"chock": {"review": {"unattestable_paths": ["src/chock/validation/"]}}}),
        encoding="utf-8",
    )

    assert unattestable_paths(repo) == ["src/chock/validation/"]
    assert unattestable_paths(repo) != sorted(DEFAULT_UNATTESTABLE)


def test_evidence_expires_when_the_content_changes(repo: Path, evidence: dict) -> None:
    """Binding to content is what stops evidence vouching for code that no longer exists."""
    (repo / "feature.txt").write_text("something else\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-q", "--amend", "--no-edit")

    assert any("stale" in f for f in verify(repo, evidence, "main"))


def test_the_evidence_file_does_not_invalidate_itself(repo: Path, evidence: dict) -> None:
    """`diff_sha` excludes the evidence directory, or nothing could ever be committed."""
    before = diff_sha(repo, "main")
    dest = repo / ".chock" / "evidence" / "x.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(evidence), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "evidence")

    assert diff_sha(repo, "main") == before
    assert verify(repo, evidence, "main") == []


def test_a_weak_attestation_still_passes(repo: Path, evidence: dict) -> None:
    """Verification says nothing about attestations, on purpose."""
    evidence["attested"] = [
        {"criterion": "satisfiability", "claim": "regex looks fine", "basis": "skimmed", "confidence": "low"}
    ]

    assert verify(repo, evidence, "main") == []


def test_attestations_are_printed_without_a_verified_marker(repo: Path, evidence: dict, tmp_path: Path) -> None:
    """The output is the only place a reader learns which claims were checked."""
    evidence["attested"] = [{"criterion": "c", "claim": "a claim", "basis": "read it in full"}]
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "-m", "chock", "review", "verify", "--repo", str(repo), "--base", "main", str(path)],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0
    assert "NOT verified" in proc.stdout
    assert "read it in full" in proc.stdout


def test_the_registry_is_not_influenced_by_evidence(repo: Path) -> None:
    """Sanity check on the trust boundary: the registry is a function of the repo alone."""
    assert set(check_registry(repo)) >= {"validate", "eval", "recompile-check", "verify"}


def test_emitting_with_uncommitted_work_is_refused(repo: Path) -> None:
    """The mistake this guard exists for, and the one I made while wiring the catalog up."""
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-B", "feat/empty")
    (repo / "wip.txt").write_text("uncommitted\n", encoding="utf-8")

    with pytest.raises(EvidenceError, match="uncommitted changes"):
        build(repo, "main", {"kind": "agent", "id": "test"}, ["validate"])


def test_an_identical_branch_is_refused_with_a_different_reason(repo: Path) -> None:
    """Same refusal, different cause. Naming which one is the whole value of the message."""
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-B", "feat/same")

    with pytest.raises(EvidenceError, match="identical to main"):
        build(repo, "main", {"kind": "agent", "id": "test"}, ["validate"])


def test_allow_empty_is_available_for_the_deliberate_case(repo: Path) -> None:
    """A guard with no escape hatch gets worked around rather than respected."""
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-B", "feat/same2")

    evidence = build(repo, "main", {"kind": "agent", "id": "test"}, ["validate"], allow_empty=True)

    assert evidence["diff_sha"] == EMPTY_DIFF_SHA


def test_verify_states_coverage_so_evidence_holds_never_implies_more(
    repo: Path, evidence: dict, tmp_path: Path
) -> None:
    """H1's harm is the false assurance, not the narrowing.

    `emit --checks` takes any subset and `verify` re-derives only what the file names, so a
    one-check file printed a bare "Evidence holds". Narrowing stays supported; what it may no
    longer do is look like full coverage.
    """
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "chock", "review", "verify", str(path), "--repo", str(repo), "--base", "main"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "coverage:" in proc.stdout, proc.stdout
    assert "NOT covered" in proc.stdout, proc.stdout
    assert "declares no `required_checks`" in proc.stdout, proc.stdout


def test_a_declared_required_set_is_enforced_and_comes_from_the_repo(repo: Path, evidence: dict) -> None:
    """The rule `unattestable` already follows, applied to checks: the checked does not choose."""
    assert verify(repo, evidence, "main") == []

    config = repo / ".chock" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("chock:\n  review:\n    required_checks: [validate, eval]\n", encoding="utf-8")
    failures = verify(repo, evidence, "main")
    assert any("does not cover the checks this repository requires" in f for f in failures), failures
    assert any("eval" in f for f in failures), failures


def test_a_required_set_cannot_be_shrunk_from_inside_the_evidence(repo: Path, evidence: dict) -> None:
    config = repo / ".chock" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("chock:\n  review:\n    required_checks: [validate, eval]\n", encoding="utf-8")
    forged = dict(evidence, required_checks=["validate"])
    assert verify(repo, forged, "main"), "evidence shrank the required set (H1)"

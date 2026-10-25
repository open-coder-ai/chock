"""Only the base defines the checks `chock review` runs; a PR that adds and requires one is bound from the merge on."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_review_require import _commit_base_config, _git, _write_config, _write_evidence

from chock.review.evidence import EvidenceError, build, command_set_hash, require, required_checks
from chock.review.policy import BUILTIN_CHECKS, check_registry, deferred_checks


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A base commit on `main` and one change on a branch."""
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


def test_a_branch_cannot_add_a_check_the_base_does_not_define(repo: Path) -> None:
    """A check is code the gate runs: only the base defines one; a head-added check is not run, or even known."""
    marker = repo / "ran.txt"
    script = ["python", "-c", f"open({str(marker)!r}, 'w').write('x')"]
    _commit_base_config(repo, {"required_checks": ["validate"]})
    _write_config(repo, {"checks": {"extra": script}, "required_checks": ["validate", "extra"]})

    assert "extra" not in check_registry(repo, "main")
    assert required_checks(repo, "main") == ["validate"]
    with pytest.raises(EvidenceError, match="unknown check"):
        build(repo, "main", {"kind": "agent", "id": "t"}, ["validate", "extra"])
    forged = dict(build(repo, "main", {"kind": "agent", "id": "t"}, ["validate"]))
    forged["verified"] = [*forged["verified"], {"check": "extra", "command": "chock x", "result": "pass"}]
    _write_evidence(repo, forged)
    assert require(repo, "main") != []
    assert not marker.exists()


def test_a_branch_may_add_and_require_a_check_it_is_required_from_the_merge_on(repo: Path) -> None:
    """The PR that introduces a check is not blocked by it, and the check never runs from the head's definition."""
    marker = repo / "ran.txt"
    script = ["python", "-c", f"open({str(marker)!r}, 'w').write('x')"]
    _commit_base_config(repo, {"required_checks": ["validate"]})
    _write_config(repo, {"checks": {"extra": script}, "required_checks": ["validate", "extra"]})

    assert required_checks(repo, "main") == ["validate"]
    assert deferred_checks(repo, "main") == ["extra"]
    _write_evidence(repo, build(repo, "main", {"kind": "agent", "id": "t"}, ["validate"]))
    assert require(repo, "main") == []
    assert not marker.exists()


def test_a_check_the_base_requires_but_does_not_define_still_fails_as_unknown(repo: Path) -> None:
    _commit_base_config(repo, {"required_checks": ["validate", "ghost"]})
    _write_config(repo, {"required_checks": ["validate", "ghost"]})

    assert required_checks(repo, "main") == ["ghost", "validate"]
    assert deferred_checks(repo, "main") == []
    _write_evidence(repo, build(repo, "main", {"kind": "agent", "id": "t"}, ["validate"]))
    assert any("ghost" in f for f in require(repo, "main"))


def test_a_check_the_base_defines_and_the_head_requires_applies_at_once(repo: Path) -> None:
    _commit_base_config(repo, {"checks": {"mine": ["python", "-c", "pass"]}, "required_checks": ["validate"]})
    _write_config(repo, {"required_checks": ["validate", "mine"]})

    assert required_checks(repo, "main") == ["mine", "validate"]
    assert deferred_checks(repo, "main") == []
    _write_evidence(repo, build(repo, "main", {"kind": "agent", "id": "t"}, ["validate"]))
    assert any("missing: mine" in f for f in require(repo, "main"))


def test_a_branch_cannot_redefine_a_builtin_the_base_requires(repo: Path) -> None:
    """The documented setup lists built-ins in `required_checks` without redefining them; the head cannot."""
    marker = repo / "ran.txt"
    script = ["python", "-c", f"open({str(marker)!r}, 'w').write('x')"]
    _commit_base_config(repo, {"required_checks": ["validate", "eval"]})
    before = command_set_hash(repo, "main")
    _write_config(repo, {"checks": {"validate": script, "eval": script}, "required_checks": ["validate", "eval"]})

    assert check_registry(repo, "main")["validate"] == BUILTIN_CHECKS["validate"]
    assert check_registry(repo, "main")["eval"] == BUILTIN_CHECKS["eval"]
    assert command_set_hash(repo, "main") == before
    assert not marker.exists()


def test_a_head_check_is_not_defined_when_the_base_has_no_config(repo: Path) -> None:
    _write_config(repo, {"checks": {"validate": ["python", "-c", "pass"], "extra": ["python", "-c", "pass"]}})

    registry = check_registry(repo, "main")

    assert registry["validate"] == BUILTIN_CHECKS["validate"]
    assert "extra" not in registry


def test_the_base_may_define_and_redefine_checks(repo: Path) -> None:
    _commit_base_config(repo, {"checks": {"validate": ["validate", "{root}", "--strict"], "mine": ["check"]}})

    registry = check_registry(repo, "main")

    assert registry["validate"] == ["validate", "{root}", "--strict"]
    assert registry["mine"] == ["check"]

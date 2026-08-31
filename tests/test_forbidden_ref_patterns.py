"""`forbidden_ref` must enforce glob patterns, and must not over-enforce them."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import init_repo, stage, write_gate

from chock.gate.runner import run

ALLOW, BLOCK = 0, 1


def _gate(tmp_path: Path, refs: list[str], event: str) -> Path:
    return write_gate(
        tmp_path,
        {
            "kind": "forbidden_ref",
            "on": [event],
            "action": "block",
            "message": "no",
            "params": {"refs": refs},
        },
    )


def _commit_verdict(tmp_path: Path, refs: list[str], branch: str) -> int:
    gate = _gate(tmp_path, refs, "commit")
    repo = init_repo(tmp_path)
    subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=repo, check=True)
    stage(repo, "a.txt", "ok\n")
    return run(gate, "pre-commit", None, repo)


def _push_verdict(tmp_path: Path, refs: list[str], ref: str) -> int:
    gate = _gate(tmp_path, refs, "push")
    return run(gate, "pre-push", f"{ref} abc {ref} def\n", tmp_path)


PATTERN_BLOCKED = [
    ("release/*", "release/1.2"),
    ("release/*", "release/2024-06"),
    ("release/*", "release/1.2/rc1"),
    ("hotfix-?", "hotfix-9"),
    ("release/[0-9]*", "release/3.1"),
]


@pytest.mark.parametrize(("pattern", "branch"), PATTERN_BLOCKED)
def test_commit_pattern_blocks(tmp_path: Path, pattern: str, branch: str) -> None:
    assert _commit_verdict(tmp_path, ["main", pattern], branch) == BLOCK


@pytest.mark.parametrize(("pattern", "branch"), PATTERN_BLOCKED)
def test_push_pattern_blocks(tmp_path: Path, pattern: str, branch: str) -> None:
    assert _push_verdict(tmp_path, ["main", pattern], f"refs/heads/{branch}") == BLOCK


PATTERN_ALLOWED = [
    ("release/*", "feature/release-notes"),
    ("release/*", "hotfix"),
    ("release/*", "release"),
    ("release/*", "prerelease/1.2"),
    ("hotfix-?", "hotfix-1234"),
    ("release/[0-9]*", "release/rc1"),
]


@pytest.mark.parametrize(("pattern", "branch"), PATTERN_ALLOWED)
def test_commit_pattern_does_not_over_match(tmp_path: Path, pattern: str, branch: str) -> None:
    assert _commit_verdict(tmp_path, ["main", pattern], branch) == ALLOW


@pytest.mark.parametrize(("pattern", "branch"), PATTERN_ALLOWED)
def test_push_pattern_does_not_over_match(tmp_path: Path, pattern: str, branch: str) -> None:
    assert _push_verdict(tmp_path, ["main", pattern], f"refs/heads/{branch}") == ALLOW


EXACT = [("main", BLOCK), ("Main", ALLOW), ("MAIN", ALLOW), ("mainline", ALLOW), ("main-2", ALLOW), ("dev", ALLOW)]


@pytest.mark.parametrize(("branch", "expected"), EXACT)
def test_commit_exact_ref_semantics_unchanged(tmp_path: Path, branch: str, expected: int) -> None:
    assert _commit_verdict(tmp_path, ["main", "master"], branch) == expected


@pytest.mark.parametrize(("branch", "expected"), EXACT)
def test_push_exact_ref_semantics_unchanged(tmp_path: Path, branch: str, expected: int) -> None:
    assert _push_verdict(tmp_path, ["main", "master"], f"refs/heads/{branch}") == expected


def test_push_ignores_non_branch_refs(tmp_path: Path) -> None:
    assert _push_verdict(tmp_path, ["release/*"], "refs/tags/release/1.2") == ALLOW

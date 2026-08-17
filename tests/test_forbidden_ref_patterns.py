"""`forbidden_ref` must enforce glob patterns, and must not over-enforce them.

A config of `protected_branches: [main, "release/*"]` validated, compiled, and passed
`recompile --check` while protecting nothing on any release branch -- silent
non-enforcement, the same failure class as a manifest format with no extractor. These
tests pin both halves: the pattern blocks what it names, and it blocks nothing else. The
negative cases matter more than the positive ones, because an over-blocking gate is the
kind users switch off.
"""

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


# --------------------------------------------------------------- patterns are enforced
PATTERN_BLOCKED = [
    ("release/*", "release/1.2"),
    ("release/*", "release/2024-06"),
    # `*` spans `/` by design: protecting `release/` protects everything under it, and a
    # nested branch is exactly the thing a user expects the namespace guard to catch.
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


# ------------------------------------------------------------------- negative space
# Over-blocking is the failure that gets a guard switched off, so every one of these must
# reach the working tree untouched.
PATTERN_ALLOWED = [
    ("release/*", "feature/release-notes"),
    ("release/*", "hotfix"),
    ("release/*", "release"),  # the namespace prefix alone is not inside the namespace
    ("release/*", "prerelease/1.2"),
    ("hotfix-?", "hotfix-1234"),  # `?` is exactly one character
    ("release/[0-9]*", "release/rc1"),
]


@pytest.mark.parametrize(("pattern", "branch"), PATTERN_ALLOWED)
def test_commit_pattern_does_not_over_match(tmp_path: Path, pattern: str, branch: str) -> None:
    assert _commit_verdict(tmp_path, ["main", pattern], branch) == ALLOW


@pytest.mark.parametrize(("pattern", "branch"), PATTERN_ALLOWED)
def test_push_pattern_does_not_over_match(tmp_path: Path, pattern: str, branch: str) -> None:
    assert _push_verdict(tmp_path, ["main", pattern], f"refs/heads/{branch}") == ALLOW


# ------------------------------------------------------- exact refs are unchanged
# A ref with no metacharacter must keep byte-identical behaviour, including case: git refs
# are case-sensitive, and `fnmatch` (as opposed to `fnmatchcase`) would fold them on Windows.
EXACT = [("main", BLOCK), ("Main", ALLOW), ("MAIN", ALLOW), ("mainline", ALLOW), ("main-2", ALLOW), ("dev", ALLOW)]


@pytest.mark.parametrize(("branch", "expected"), EXACT)
def test_commit_exact_ref_semantics_unchanged(tmp_path: Path, branch: str, expected: int) -> None:
    assert _commit_verdict(tmp_path, ["main", "master"], branch) == expected


@pytest.mark.parametrize(("branch", "expected"), EXACT)
def test_push_exact_ref_semantics_unchanged(tmp_path: Path, branch: str, expected: int) -> None:
    assert _push_verdict(tmp_path, ["main", "master"], f"refs/heads/{branch}") == expected


def test_push_ignores_non_branch_refs(tmp_path: Path) -> None:
    # A tag named `release/1.2` is not a branch; the guard is about branches only.
    assert _push_verdict(tmp_path, ["release/*"], "refs/tags/release/1.2") == ALLOW

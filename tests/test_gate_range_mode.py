"""`--event ci` (commit-range mode): the gate must judge a PR's base...head range, not the
staged index, since a CI checkout has no staged index and index-mode scanning finds nothing.

Each test builds a real throwaway git repo (the pattern `eval/execute.py` uses), because for
"does the gate block this range" there is an observable answer -- asking whether it sounds
right is the wrong tool.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import init_repo, write_gate

from chock.gate.runner import run

SECRET_PARAMS = {"scan": "added_lines", "content_pattern": r"(?i)(AKIA[0-9A-Z]{16})"}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _write(repo: Path, rel: str, content: str) -> None:
    (repo / rel).write_text(content, encoding="utf-8")


def _base_repo(tmp_path: Path) -> tuple[Path, str]:
    """A repo with one commit on a base branch whose name we control -- CI environments vary
    `init.defaultBranch` between `main` and `master`, and this must not depend on that.
    """
    repo = init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "trunk")
    _write(repo, "app.py", "x = 1\n")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "base")
    return repo, "trunk"


def _detach(repo: Path) -> None:
    """Simulate a CI checkout: HEAD points at a commit, not a branch."""
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout
    _git(repo, "checkout", "-q", sha.strip())


def test_secret_added_on_pr_branch_is_blocked(tmp_path: Path) -> None:
    """A secret introduced anywhere in the PR range blocks, even though nothing is staged."""
    repo, base = _base_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feature")
    _write(repo, "secret.py", 'KEY = "AKIAIOSFODNN7EXAMPLE"\n')  # pragma: allowlist secret
    _git(repo, "add", "secret.py")
    _git(repo, "commit", "-m", "add secret")

    gate = write_gate(
        tmp_path,
        {"kind": "content_regex", "on": ["commit"], "action": "block", "message": "secret", "params": SECRET_PARAMS},
    )
    assert run(gate, "ci", None, repo, base=base) == 1


def test_secret_already_on_base_untouched_is_not_blocked(tmp_path: Path) -> None:
    """Only content the PR ADDS counts -- a pre-existing secret the PR never touches must not fire."""
    repo, base = _base_repo(tmp_path)
    _write(repo, "secret.py", 'KEY = "AKIAIOSFODNN7EXAMPLE"\n')  # pragma: allowlist secret
    _git(repo, "add", "secret.py")
    _git(repo, "commit", "-m", "add pre-existing secret to base")
    _git(repo, "checkout", "-q", "-b", "feature")
    _write(repo, "secret.py", 'KEY = "AKIAIOSFODNN7EXAMPLE"\ny = 2\n')  # pragma: allowlist secret
    _git(repo, "add", "secret.py")
    _git(repo, "commit", "-m", "unrelated edit")

    gate = write_gate(
        tmp_path,
        {"kind": "content_regex", "on": ["commit"], "action": "block", "message": "secret", "params": SECRET_PARAMS},
    )
    assert run(gate, "ci", None, repo, base=base) == 0


def test_clean_range_allows(tmp_path: Path) -> None:
    repo, base = _base_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feature")
    _write(repo, "app.py", "x = 1\ny = 2\n")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "clean change")

    gate = write_gate(
        tmp_path,
        {"kind": "content_regex", "on": ["commit"], "action": "block", "message": "secret", "params": SECRET_PARAMS},
    )
    assert run(gate, "ci", None, repo, base=base) == 0


def test_dependency_gate_reports_only_deps_the_range_adds(tmp_path: Path) -> None:
    repo, base = _base_repo(tmp_path)
    _write(repo, "requirements.txt", "requests\n")
    _git(repo, "add", "requirements.txt")
    _git(repo, "commit", "-m", "add manifest to base")
    _git(repo, "checkout", "-q", "-b", "feature")
    _write(repo, "requirements.txt", "requests\nnumpy\n")
    _git(repo, "add", "requirements.txt")
    _git(repo, "commit", "-m", "add numpy")
    (repo / "allow.txt").write_text("requests\n", encoding="utf-8")

    gate = write_gate(
        tmp_path,
        {
            "kind": "dependency_allowlist",
            "on": ["commit"],
            "action": "block",
            "message": "unlisted dep",
            "params": {"manifests": ["requirements.txt"], "allowlist_file": "allow.txt"},
        },
    )
    assert run(gate, "ci", None, repo, base=base) == 1


def test_dependency_gate_allows_when_only_pre_existing_deps_present(tmp_path: Path) -> None:
    """`requests` was already unlisted on base; the PR does not add it, so it must not fire."""
    repo, base = _base_repo(tmp_path)
    _write(repo, "requirements.txt", "requests\n")
    _git(repo, "add", "requirements.txt")
    _git(repo, "commit", "-m", "add manifest to base")
    _git(repo, "checkout", "-q", "-b", "feature")
    _write(repo, "requirements.txt", "requests\n# comment\n")
    _git(repo, "add", "requirements.txt")
    _git(repo, "commit", "-m", "touch manifest, add nothing")
    (repo / "allow.txt").write_text("numpy\n", encoding="utf-8")

    gate = write_gate(
        tmp_path,
        {
            "kind": "dependency_allowlist",
            "on": ["commit"],
            "action": "block",
            "message": "unlisted dep",
            "params": {"manifests": ["requirements.txt"], "allowlist_file": "allow.txt"},
        },
    )
    assert run(gate, "ci", None, repo, base=base) == 0


def test_forbidden_ref_head_ref_override_blocks(tmp_path: Path) -> None:
    """A CI checkout is detached HEAD; `--head-ref` supplies the branch git cannot see."""
    repo, base = _base_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "release/1.0")
    _detach(repo)

    gate = write_gate(
        tmp_path,
        {
            "kind": "forbidden_ref",
            "on": ["commit"],
            "action": "block",
            "message": "no",
            "params": {"refs": ["release/*"]},
        },
    )
    assert run(gate, "ci", None, repo, base=base, head_ref="release/1.0") == 1


def test_forbidden_ref_detached_head_without_override_allows(tmp_path: Path) -> None:
    """No --head-ref, detached HEAD: `current_branch()` sees nothing, so this must allow, not
    false-block -- a gate that fires when it cannot judge the branch gets deleted within a week.
    """
    repo, base = _base_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "release/1.0")
    _detach(repo)

    gate = write_gate(
        tmp_path,
        {
            "kind": "forbidden_ref",
            "on": ["commit"],
            "action": "block",
            "message": "no",
            "params": {"refs": ["release/*"]},
        },
    )
    assert run(gate, "ci", None, repo, base=base) == 0


def test_push_only_gate_does_not_fire_in_ci_mode(tmp_path: Path) -> None:
    """CI has no equivalent of "pushing to a ref"; promoting a push-only gate would invent an
    enforcement point the manifest never declared.
    """
    repo, base = _base_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "main")

    gate = write_gate(
        tmp_path,
        {"kind": "forbidden_ref", "on": ["push"], "action": "block", "message": "no", "params": {"refs": ["main"]}},
    )
    assert run(gate, "ci", None, repo, base=base, head_ref="main") == 0


def test_ci_event_requires_base_argument() -> None:
    import pytest

    from chock.gate.runner import main

    with pytest.raises(SystemExit) as exc:
        main(["run", "--gate", "no.json", "--event", "ci"])
    assert exc.value.code == 2

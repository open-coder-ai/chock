"""The scaffolded CI workflow refuses a pull request whose policy set is weaker than its base's."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from chock.scaffold.install_ci import WORKFLOW_TEMPLATE

JOB = yaml.safe_load(WORKFLOW_TEMPLATE)["jobs"]["chock-gate"]
STEPS = {step["name"]: step for step in JOB["steps"] if "name" in step}
BASELINE = STEPS["Policy set is no weaker than the base branch"]
BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None or os.name == "nt", reason="runs the step as the ubuntu runner does")


def test_the_baseline_step_runs_on_pull_requests_against_the_base_branch() -> None:
    assert BASELINE["if"] == "github.event_name == 'pull_request'"
    assert BASELINE["env"] == {"BASE_REF": "${{ github.base_ref }}"}
    assert BASELINE["run"] == 'chock check --only baseline --base "origin/$BASE_REF"'
    assert "continue-on-error" not in BASELINE


def test_no_run_step_interpolates_an_expression_into_shell_text() -> None:
    assert [name for name, step in STEPS.items() if "${{" in step.get("run", "")] == []


def test_the_baseline_runs_before_the_gates() -> None:
    names = list(STEPS)
    assert names.index(BASELINE["name"]) < names.index("Run compiled CI gates (commit-range mode)")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _commit_config(repo: Path, body: str, message: str) -> None:
    (repo / ".chock").mkdir(exist_ok=True)
    (repo / ".chock" / "config.yaml").write_text(body, encoding="utf-8")
    _git(repo, "add", ".chock/config.yaml")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--no-gpg-sign", "-m", message)


@pytest.fixture
def pull_request(tmp_path: Path) -> Path:
    """A checkout of a pull request branch whose base `main` is only present as origin/main."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _commit_config(origin, "policies:\n  disabled: []\n", "base")
    head = tmp_path / "head"
    _git(tmp_path, "clone", "-q", str(origin), str(head))
    _git(head, "checkout", "-q", "-b", "feature")
    shim = tmp_path / "bin" / "chock"
    shim.parent.mkdir()
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m chock "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    return head


def _run_step(head: Path, base_ref: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "BASE_REF": base_ref, "PATH": f"{head.parent / 'bin'}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run(
        [BASH, "-e", "-c", BASELINE["run"]], cwd=head, env=env, capture_output=True, text=True, check=False
    )


@needs_bash
def test_the_step_refuses_a_pull_request_that_disables_a_policy(pull_request: Path) -> None:
    _commit_config(pull_request, "policies:\n  disabled: [scan-secrets]\n", "switch a gate off")
    result = _run_step(pull_request, "main")
    assert result.returncode == 1
    assert "scan-secrets" in result.stdout + result.stderr


@needs_bash
def test_the_step_passes_a_pull_request_that_keeps_the_policy_set(pull_request: Path) -> None:
    result = _run_step(pull_request, "main")
    assert result.returncode == 0, result.stdout + result.stderr


@needs_bash
def test_a_base_that_does_not_resolve_fails_the_step(pull_request: Path) -> None:
    assert _run_step(pull_request, "no-such-branch").returncode != 0


@needs_bash
def test_a_branch_name_with_shell_metacharacters_stays_data(pull_request: Path) -> None:
    result = _run_step(pull_request, 'main" ; touch pwned ; echo "')
    assert result.returncode != 0
    assert not (pull_request / "pwned").exists()

"""Workflow triggers that hand a fork's code repository-scoped secrets."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))

UNSAFE_TRIGGERS = {"pull_request_target", "workflow_run"}


def test_there_are_workflows_to_check() -> None:
    """A glob that silently matches nothing would make every test below vacuously pass."""
    assert WORKFLOWS, "no workflows found; this file's guarantees would be empty"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_workflow_runs_forked_code_with_our_secrets(path: Path) -> None:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))

    triggers = workflow.get(True) or workflow.get("on") or {}
    names = set(triggers) if isinstance(triggers, dict) else set(triggers if isinstance(triggers, list) else [triggers])

    unsafe = names & UNSAFE_TRIGGERS
    assert not unsafe, (
        f"{path.name} triggers on {sorted(unsafe)}, which runs with this repository's secrets "
        f"against contributor-controlled input. Use `pull_request` instead, and if the job "
        f"genuinely needs a token, split it so the privileged half never checks out fork code."
    )


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_workflow_checks_out_an_untrusted_ref(path: Path) -> None:
    """`actions/checkout` with a PR-controlled ref is the other half of the same hazard."""
    text = path.read_text(encoding="utf-8")
    for marker in ("github.event.pull_request.head.sha", "github.event.pull_request.head.ref"):
        assert marker not in text, (
            f"{path.name} checks out {marker}. Combined with a privileged trigger this runs a "
            f"contributor's code with this repository's token."
        )


def test_every_lifecycle_check_has_its_own_ci_step() -> None:
    """CI runs each sub-check as its own step, so a new one in CHECKS is invisible until listed."""
    from chock.lifecycle import CHECKS

    ci = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    missing = [name for name in CHECKS if f"chock check --only {name}" not in ci]
    assert not missing, (
        f".github/workflows/ci.yml has no step for {missing}. Bare `chock check` runs every entry "
        f"in CHECKS, but CI runs them one --only at a time, so a check added to CHECKS without a "
        f"step here never gates a pull request. Add one beside the others in the `validate` job."
    )

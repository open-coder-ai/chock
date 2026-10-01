"""The CI workflow chock installs uploads the SARIF log, and only that step may fail quietly."""

from __future__ import annotations

import re

import yaml

from chock.scaffold.install_ci import WORKFLOW_TEMPLATE

JOB = yaml.safe_load(WORKFLOW_TEMPLATE)["jobs"]["chock-gate"]
STEPS = {step["name"]: step for step in JOB["steps"] if "name" in step}
UPLOAD = STEPS["Upload SARIF to code scanning"]
PINNED = re.compile(r"github/codeql-action/upload-sarif@[0-9a-f]{40}")


def test_the_upload_is_pinned_to_a_commit_and_runs_after_a_failed_gate() -> None:
    assert PINNED.fullmatch(UPLOAD["uses"])
    assert "always()" in UPLOAD["if"]
    assert UPLOAD["with"]["category"] == "chock"


def test_only_the_upload_continues_on_error() -> None:
    assert [name for name, step in STEPS.items() if step.get("continue-on-error")] == [UPLOAD["name"]]


def test_the_write_permission_is_the_jobs_own_and_only_security_events() -> None:
    assert JOB["permissions"] == {"contents": "read", "security-events": "write"}
    assert "permissions" not in yaml.safe_load(WORKFLOW_TEMPLATE)


def test_the_log_is_written_after_the_gates_and_before_the_upload() -> None:
    names = list(STEPS)
    write = STEPS["Write SARIF findings"]
    assert (
        names.index("Run compiled CI gates (commit-range mode)")
        < names.index(write["name"])
        < names.index(UPLOAD["name"])
    )
    assert write["if"] == "always()"
    assert "--format sarif" in write["run"] and "--event ci" in write["run"]
    assert write["run"].count("$RUNNER_TEMP/chock.sarif") == 1
    assert UPLOAD["with"]["sarif_file"] == "${{ runner.temp }}/chock.sarif"

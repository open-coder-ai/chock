"""Workflow triggers that hand a fork's code repository-scoped secrets.

`pull_request_target` runs with the *base* repository's token and secrets, while checking out
whatever the pull request asks for. On a public repo that is one careless `ref:` away from
handing a stranger's branch a write-scoped `GITHUB_TOKEN` -- the standard way a public
repository with CI automation gets compromised.

Both repos are clean today: every workflow triggers on `pull_request`. The temptation arrives
the first time someone wants a bot to label, comment on, or auto-fix a fork PR, because
`pull_request` cannot do it and `pull_request_target` can. That is precisely the moment nobody
is thinking about the token.

So this is written down as a control rather than left as a habit. If a future workflow genuinely
needs it, deleting this test is the reviewable act that says so.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))

#: Triggers that run with the base repo's secrets against contributor-controlled input.
UNSAFE_TRIGGERS = {"pull_request_target", "workflow_run"}


def test_there_are_workflows_to_check() -> None:
    """A glob that silently matches nothing would make every test below vacuously pass."""
    assert WORKFLOWS, "no workflows found; this file's guarantees would be empty"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_workflow_runs_forked_code_with_our_secrets(path: Path) -> None:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))

    # `on:` is the YAML 1.1 boolean `true`, which PyYAML helpfully parses for us. Reading it
    # as the string "on" finds nothing and passes every file.
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
    """`actions/checkout` with a PR-controlled ref is the other half of the same hazard.

    Harmless under `pull_request`, which already runs unprivileged. Checked anyway, because the
    pair is what causes the compromise and a later trigger change would otherwise arm it
    silently.
    """
    text = path.read_text(encoding="utf-8")
    for marker in ("github.event.pull_request.head.sha", "github.event.pull_request.head.ref"):
        assert marker not in text, (
            f"{path.name} checks out {marker}. Combined with a privileged trigger this runs a "
            f"contributor's code with this repository's token."
        )

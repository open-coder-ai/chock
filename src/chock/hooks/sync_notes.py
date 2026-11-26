"""What `chock sync` says about each wired agent: agentseam's pre-tool row, and whether chock has seen it run."""

from __future__ import annotations

from pathlib import Path

from agentseam import contract, tier_table

from chock import evidence, vendors

#: Surfaces sync installs; plugin-hook witnesses `chock install` only, git-hook-env a marker only.
_HOOK_SURFACES = ("pre-tool-use", "agent-hooks")

UNTESTED = (
    "Untested: chock has not witnessed its hooks run in this client; the wiring follows agentseam's record. "
    "What you see there is wanted as evidence: open-coder-ai/agentseam issues labelled 'evidence wanted'."
)


PROMPT_SUBMIT_UNTESTED = (
    "prompt-submit: untested -- no live refusal of a prompt is recorded for this client yet, "
    "so a prompt_submit gate here is wiring, not a witnessed block."
)
PROMPT_SUBMIT_WITNESSED = (
    "prompt-submit: witnessed -- a live refusal of a prompt is recorded for this client ({client}, {date})."
)
PROMPT_SUBMIT_NO_HOOK = (
    "prompt-submit: no hook written -- agentseam grades this client detect or none at that event: "
    "it can notice a prompt, not refuse one, so a prompt_submit gate does nothing here."
)


def tier_line(vendor: str, event: str = contract.PRE_TOOL, label: str = "pre-tool") -> str | None:
    """agentseam's row for `vendor` at `event`, its basis carried through; None where it has no row."""
    row = next((r for r in tier_table.rows(event) if r["agent"] == vendor), None)
    if row is None:
        return None
    return (
        f"{label}: {row['tier']}, {row['grade']}, fail mode {row['fail_mode']}"
        f" (agentseam basis {row['basis']}, recorded {row['recorded']})"
    )


def prompt_submit_lines(vendor: str, repo_root: Path | None) -> list[str]:
    """What sync says about prompt-submit gates for `vendor`, only in a repo that compiled one.

    A blocking agent gets agentseam's row and the witnessed or untested note; a detect-only one is told it got no hook.
    """
    if repo_root is None or not any((Path(repo_root) / ".chock" / "compiled").glob("*/prompt-submit/*-gate.json")):
        return []
    if vendor in vendors.prompt_submit_vendors():
        line = tier_line(vendor, contract.PROMPT_SUBMIT, "prompt-submit")
        seen = evidence.witness(vendor, "prompt-submit")
        note = PROMPT_SUBMIT_WITNESSED.format(client=seen.client, date=seen.date) if seen else PROMPT_SUBMIT_UNTESTED
        return [text for text in (line, note) if text]
    return [PROMPT_SUBMIT_NO_HOOK]


def witnessed(vendor: str, *, ledger: tuple[evidence.Witness, ...] | None = None) -> bool:
    """Whether the ledger holds a live run of chock's repo hooks deciding in `vendor`'s client."""
    return any(evidence.witness(vendor, surface, ledger=ledger) for surface in _HOOK_SURFACES)


def notes(vendor: str, repo_root: Path | None = None) -> list[str]:
    """The lines sync prints under a vendor it registered hooks for."""
    lines = [line for line in (tier_line(vendor),) if line]
    if not witnessed(vendor):
        lines.append(UNTESTED)
    lines += prompt_submit_lines(vendor, repo_root)
    return [f"  {vendor}: {line}" for line in lines]

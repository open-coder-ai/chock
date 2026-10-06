"""A guardrails member switched off in the repo's `.chock/guardrails.json` against the base: a loosening.

The file is read with the runtime's own parser (`chock.guardrails.toggle`), so the check and the hook agree:
text the runtime ignores switches nothing off on either side. Deleting a committed file hands the switches
to the user-level `~/.chock/guardrails.json`, so that is a loosening too, whatever the base said.
"""

from __future__ import annotations

from pathlib import Path

from chock.guardrails import toggle
from chock.validation.report import Finding, Report
from chock.validation.selection_baseline import Kind, SelectionInvalidError
from chock.validation.selection_source import NOT_COMPARED, selection_text

GUARDRAILS = Kind(
    toggle.FILENAME,
    frozenset({toggle.VERSION}),
    frozenset(toggle.STATES),
    toggle.ON,
    verdict_ends_rules=False,
    lenient=False,
    fallback="deleting the repo file hands the switches to ~/.chock/guardrails.json",
)
_CATEGORY = "policy_baseline"


def _toggles(text: str | None) -> dict[str, dict[str, str]]:
    """What the runtime reads from `text`: no file, or an invalid one, switches nothing off."""
    if text is None:
        return {}
    try:
        return toggle.parse(text)
    except toggle.ToggleError:
        return {}


def switched_off(base_text: str | None, head_text: str | None) -> list[str]:
    """Each member the head switches off that the base left on, as `<bundle>/<policy-id>: on -> off`."""
    if base_text is not None and head_text is None:
        return [str(GUARDRAILS.fallback)]
    base, head = _toggles(base_text), _toggles(head_text)
    return [
        f"{bundle}/{policy_id}: on -> off"
        for bundle, members in sorted(head.items())
        for policy_id, state in sorted(members.items())
        if state == toggle.OFF and toggle.state(base, bundle, policy_id) != toggle.OFF
    ]


def check_guardrails(repo_root: Path, base: str, report: Report) -> None:
    """One error per member `.chock/guardrails.json` switches off against `base`, or a file that cannot be compared."""
    path = str(Path(repo_root) / GUARDRAILS.filename)
    try:
        found = switched_off(selection_text(repo_root, GUARDRAILS, base), selection_text(repo_root, GUARDRAILS, None))
    except (SelectionInvalidError, OSError, UnicodeDecodeError) as exc:
        report.add(Finding(path, _CATEGORY, "error", f"{exc}{NOT_COMPARED}"))
        return
    for item in found:
        msg = (
            f"{GUARDRAILS.filename}: {item} -- looser than {base}. A guardrail is switched off in a pull request "
            "a human approves, never as a side effect of the change that needed it gone."
        )
        report.add(Finding(path, _CATEGORY, "error", msg))

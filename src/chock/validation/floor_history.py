"""The floor's per-commit pass: each commit in merge-base..head judged with the base's content gates.

The cumulative diff misses a secret added in one commit and removed in the next; this pass does not.
A line the base already has is not the pull request's, and a waiver the pull request adds is not
honoured, so the gates run with no waiver pattern and lines present at the base are dropped.
"""

from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path

from chock.display import inert
from chock.history import gitlog
from chock.history.gates import RULE_CONTENT, load_rules
from chock.history.scan import Finding, Limits, scan
from chock.validation.floor_git import FloorError, Revision

_COMPILED = ".chock/compiled/"
_SHORT = 12


def _introduced(finding: Finding, head: Revision, at_base: tuple[Revision, ...]) -> bool:
    """Whether the finding is the pull request's: its line (or path) is not already at the base."""
    if finding.rule != RULE_CONTENT or not finding.line:
        return not any(rev.has(finding.path) for rev in at_base)
    commit = Revision(head.repo, finding.commit)
    lines = (commit.text(finding.path) or "").splitlines()
    line = lines[finding.line - 1] if finding.line <= len(lines) else None
    return line is None or not any(line in (rev.text(finding.path) or "").splitlines() for rev in at_base)


def history_findings(repo: Path, base: Revision, head: Revision, fork: str) -> tuple[list[str], list[str]]:
    """(refusals, notes) of the per-commit pass; FloorError when it cannot judge."""
    with tempfile.TemporaryDirectory(prefix="chock-floor-history-") as scratch:
        root = Path(scratch)
        base.materialise(_COMPILED, root)
        try:
            rules, _skipped = load_rules(root)
        except gitlog.HistoryError as exc:
            if not root.joinpath(_COMPILED).is_dir() or "no installed content gates" in str(exc):
                return [], ["history: the base has no content gates; per-commit pass not run"]
            msg = f"history: {exc}"
            raise FloorError(msg) from exc
        rules = [dataclasses.replace(rule, pragma_pattern=None) for rule in rules]
        try:
            report = scan(repo, rules, fork, Limits(), head.sha)
        except gitlog.HistoryError as exc:
            msg = f"history: {exc}"
            raise FloorError(msg) from exc
    at_base = (base, Revision(repo, fork))
    lines = [
        f"{f.policy} [history]: {f.commit[:_SHORT]} {inert(f.path)}{f':{f.line}' if f.line else ''} ({f.rule})"
        for f in report.findings
        if _introduced(f, head, at_base)
    ]
    return lines, []

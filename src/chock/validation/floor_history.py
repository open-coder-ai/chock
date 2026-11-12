"""The floor's per-commit pass: each commit in merge-base..head judged with the base's content gates.

The cumulative diff misses a secret added in one commit and removed in the next; this pass does not.
A line the base already has is not the pull request's, and a waiver the pull request adds is not
honoured, so the gates run with no waiver pattern and lines present at the base are dropped.

It fails closed: a range longer than the commit limit, or a blob it does not judge, is undecided,
never a silent skip. Binary blobs are judged too (bytes that are not utf-8 are read as latin-1).
"""

from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path

from chock.display import inert
from chock.gate.runner import GateContext
from chock.history import gitlog
from chock.history.gates import RULE_CONTENT, load_rules
from chock.history.scan import Finding, Limits, scan
from chock.validation.floor_git import FloorError, Revision

_COMPILED = ".chock/compiled/"
_POLICIES = ".agents/policies/"
_SURFACES = ("ci-gate", "git-hook")
_SHORT = 12
#: The largest blob the floor reads into memory to judge; a larger one is undecided, named by commit and path.
FLOOR_MAX_BLOB_BYTES = 64 * 1024 * 1024
NO_CONTENT_GATES = "history: the base has no content gates on either surface; per-commit pass not run"


def _introduced(finding: Finding, head: Revision, at_base: tuple[Revision, ...]) -> bool:
    """Whether the finding is the pull request's: its line (or path) is not already at the base."""
    if finding.rule != RULE_CONTENT or not finding.line:
        return not any(rev.has(finding.path) for rev in at_base)
    commit = Revision(head.repo, finding.commit)
    lines = (commit.text(finding.path) or "").splitlines()
    line = lines[finding.line - 1] if finding.line <= len(lines) else None
    return line is None or not any(line in (rev.text(finding.path) or "").splitlines() for rev in at_base)


def _limits() -> Limits:
    return Limits(max_blob_bytes=FLOOR_MAX_BLOB_BYTES, judge_binary=True)


def history_findings(
    repo: Path, base: Revision, head: Revision, fork: str, exempt: frozenset[str] = frozenset()
) -> tuple[list[str], list[str]]:
    """(refusals, notes) of the per-commit pass; FloorError (undecided) when it cannot judge all of it.

    `exempt` are the packs whose lock entry the pull request changed: only their source folder is skipped.
    """
    with tempfile.TemporaryDirectory(prefix="chock-floor-history-") as scratch:
        root = Path(scratch)
        base.materialise(_COMPILED, root)
        try:
            rules, _skipped = load_rules(root, _SURFACES)
        except gitlog.HistoryError as exc:
            if "no installed content gates" in str(exc):
                return [], [NO_CONTENT_GATES]
            msg = f"history: {exc}"
            raise FloorError(msg) from exc
        rules = [
            dataclasses.replace(
                rule,
                pragma_pattern=None,
                judge=GateContext(
                    repo_root=repo,
                    scope=rule.judge.scope,
                    own=(f"{_POLICIES}{rule.policy}/",) if rule.policy in exempt else (),
                ),
            )
            for rule in rules
        ]
        limits = _limits()
        try:
            report = scan(repo, rules, fork, limits, head.sha)
        except gitlog.HistoryError as exc:
            msg = f"history: {exc}"
            raise FloorError(msg) from exc
    if report.truncated:
        msg = (
            f"history: {fork[:_SHORT]}..{head.sha[:_SHORT]} holds more than {limits.max_commits} commits; "
            "the commits past the limit were not judged"
        )
        raise FloorError(msg)
    if report.unread:
        named = "; ".join(f"{c[:_SHORT]} {inert(p)} ({why})" for c, p, why in report.unread)
        msg = f"history: blobs not judged: {named}"
        raise FloorError(msg)
    at_base = (base, Revision(repo, fork))
    lines = [
        f"{f.policy} [history]: {f.commit[:_SHORT]} {inert(f.path)}{f':{f.line}' if f.line else ''} ({f.rule})"
        for f in report.findings
        if _introduced(f, head, at_base)
    ]
    return lines, []

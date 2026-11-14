"""The floor's per-commit pass: each commit in base..head judged with the base's content gates.

The cumulative diff misses a secret added in one commit and removed in the next; this pass does not.
Each blob a commit adds or changes outside the control plane is judged whole, in every reading of
`scan.floor_texts`, with no waiver; a finding whose line (same reading, same digest) the base already
has at that path is not the pull request's. It fails closed: a range past the commit limit, or a blob
over the size limit, is undecided, naming the commit and path.
Not seen: other encodings (utf-32, compressed or encoded content), commit messages, file names.
"""

from __future__ import annotations

import dataclasses
import tempfile
from collections.abc import Callable
from pathlib import Path

from chock.display import inert
from chock.gate.runner import GateContext
from chock.history import gitlog
from chock.history.gates import RULE_CONTENT, load_rules
from chock.history.scan import Finding, Limits, _digest, floor_lines, scan
from chock.validation.floor_git import FloorError, Revision

_COMPILED = ".chock/compiled/"
_SURFACES = ("ci-gate", "git-hook")
_SHORT = 12
#: The largest blob the floor reads into memory to judge; a larger one is undecided, named by commit and path.
FLOOR_MAX_BLOB_BYTES = 64 * 1024 * 1024
NO_CONTENT_GATES = "history: the base has no content gates on either surface; per-commit pass not run"


def _introduced(finding: Finding, base: Revision) -> bool:
    """Whether the finding is the pull request's: its line (or, for a path finding, its path) is not at the base."""
    if finding.rule != RULE_CONTENT:
        return not base.has(finding.path)
    data = base.blob(finding.path)
    return data is None or finding.key not in {_digest(line) for line in floor_lines(data)}


def _report(repo: Path, base: Revision, head: Revision, limits: Limits):
    with tempfile.TemporaryDirectory(prefix="chock-floor-history-") as scratch:
        root = Path(scratch)
        base.materialise(_COMPILED, root)
        try:
            rules, _skipped = load_rules(root, _SURFACES)
        except gitlog.HistoryError as exc:
            if "no installed content gates" in str(exc):
                return None
            msg = f"history: {exc}"
            raise FloorError(msg) from exc
        rules = [
            dataclasses.replace(rule, pragma_pattern=None, judge=GateContext(repo_root=repo, scope=rule.judge.scope))
            for rule in rules
        ]
        try:
            return scan(repo, rules, base.sha, limits, head.sha)
        except gitlog.HistoryError as exc:
            msg = f"history: {exc}"
            raise FloorError(msg) from exc


def history_findings(
    repo: Path, base: Revision, head: Revision, control_plane: Callable[[str], bool]
) -> tuple[list[tuple[str, str]], list[str]]:
    """((policy, finding) per refusal candidate, notes) of the per-commit pass; FloorError (undecided) when it
    cannot judge all of it."""
    limits = Limits(max_blob_bytes=FLOOR_MAX_BLOB_BYTES, judge_binary=True, renames=False)
    report = _report(repo, base, head, limits)
    if report is None:
        return [], [NO_CONTENT_GATES]
    if report.truncated:
        msg = (
            f"history: {base.sha[:_SHORT]}..{head.sha[:_SHORT]} holds more than {limits.max_commits} commits; "
            "the commits past the limit were not judged"
        )
        raise FloorError(msg)
    unread = [(c, p, why) for c, p, why in report.unread if not control_plane(p)]
    if unread:
        named = "; ".join(f"{c[:_SHORT]} {inert(p)} ({why})" for c, p, why in unread)
        msg = f"history: blobs not judged: {named}"
        raise FloorError(msg)
    found = [
        (f.policy, f"{f.commit[:_SHORT]} {inert(f.path)}{f':{f.line}' if f.line else ''} ({f.rule})")
        for f in report.findings
        if not control_plane(f.path) and _introduced(f, base)
    ]
    return found, []

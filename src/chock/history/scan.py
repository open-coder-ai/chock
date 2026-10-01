"""Judge the blobs a repository's history introduced with the installed content gates."""

from __future__ import annotations

import contextlib
import hashlib
import signal
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from chock.history import gitlog
from chock.history.gates import RULE_CONTENT, RULE_PATH, Rule

DEFAULT_MAX_COMMITS = 5000
DEFAULT_MAX_BLOB_BYTES = 1_048_576
DEFAULT_TIME_BUDGET = 1800
#: Seconds one gate may spend on one blob; a repo-supplied pattern can be catastrophic.
BLOB_SECONDS = 10
_PROGRESS_EVERY = 500

Judged = dict[str, tuple[list[tuple[int, int, str]], set[int]]]


@dataclass
class Finding:
    commit: str
    path: str
    line: int | None
    rule: str
    policy: str

    def as_dict(self) -> dict[str, object]:
        return {"commit": self.commit, "path": self.path, "line": self.line, "rule": self.rule, "policy": self.policy}


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    commits: int = 0
    blobs_scanned: int = 0
    skipped_binary: int = 0
    skipped_oversize: int = 0
    skipped_submodules: int = 0
    truncated: bool = False
    shallow: bool = False


@dataclass(frozen=True)
class Limits:
    max_commits: int = DEFAULT_MAX_COMMITS
    max_blob_bytes: int = DEFAULT_MAX_BLOB_BYTES
    allow_shallow: bool = False
    time_budget: int = DEFAULT_TIME_BUDGET


def _say(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


@contextlib.contextmanager
def _gate_budget(policy: str) -> Iterator[None]:
    """Turn one gate running past BLOB_SECONDS into an error naming it (POSIX main thread; else unbounded)."""
    if not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        yield
        return

    def expired(_signum: int, _frame: object) -> None:
        raise gitlog.HistoryError(f"gate {policy} ran over {BLOB_SECONDS}s on one blob (catastrophic pattern?)")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, BLOB_SECONDS)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _judge_blob(rules: list[Rule], data: bytes) -> tuple[list[tuple[int, int, str]], set[int]]:
    """(rule index, line number, line digest) per hit, and the rules whose waiver pragma the blob carries."""
    text = data.decode("utf-8", "replace")
    lines = text.splitlines()
    hits: list[tuple[int, int, str]] = []
    waived: set[int] = set()
    for index, rule in enumerate(rules):
        with _gate_budget(rule.policy):
            hits += [(index, n, _digest(lines[n - 1])) for n in rule.hits(text)]
            if rule.pragma_re and rule.pragma_re.search(text):
                waived.add(index)
    return hits, waived


def _read_judged(repo: Path, rules: list[Rule], oids: list[str], limits: Limits, report: Report) -> Judged:
    """Judge each distinct blob once; oversize and binary ones are skipped and counted, a missing one is an error."""
    sizes = gitlog.blob_sizes(repo, oids)
    missing = [o for o in oids if o not in sizes]
    if missing:
        raise gitlog.HistoryError(f"{len(missing)} blob(s) missing from the object database, e.g. {missing[0]}")
    report.skipped_oversize = sum(1 for o in oids if sizes[o] > limits.max_blob_bytes)
    wanted = [o for o in oids if 0 < sizes[o] <= limits.max_blob_bytes]
    deadline = time.monotonic() + limits.time_budget
    judged: Judged = {}
    for done, (oid, data) in enumerate(gitlog.read_blobs(repo, wanted, sizes), start=1):
        if time.monotonic() > deadline:
            raise gitlog.HistoryError(
                f"time budget of {limits.time_budget}s exceeded; narrow with --since or --max-commits"
            )
        if gitlog.is_binary(data):
            report.skipped_binary += 1
        else:
            judged[oid] = _judge_blob(rules, data)
            report.blobs_scanned += 1
        if done % _PROGRESS_EVERY == 0:
            _say(f"history: read {done}/{len(wanted)} blobs")
    return judged


def _collect(touched: list[gitlog.Touch], rules: list[Rule], judged: Judged) -> list[Finding]:
    """Findings oldest commit first; a line that persists across edits is reported once, where it entered."""
    found: list[Finding] = []
    seen: set[tuple[str, str, str]] = set()

    def add(item: gitlog.Touch, rule: Rule, kind: str, line: int | None, key: str) -> None:
        marker = (item.path, rule.policy, key)
        if marker not in seen:
            seen.add(marker)
            found.append(Finding(item.commit, item.path, line, kind, rule.policy))

    for item in touched:
        hits, waived = judged.get(item.oid, ([], set()))
        for index, rule in enumerate(rules):
            if rule.covers(item.path) and rule.path_re and rule.path_re.search(item.path) and index not in waived:
                add(item, rule, RULE_PATH, None, RULE_PATH)
        for index, number, digest in hits:
            if rules[index].covers(item.path):
                add(item, rules[index], RULE_CONTENT, number, digest)
    return found


def scan(repo: Path, rules: list[Rule], since: str | None, limits: Limits) -> Report:
    report = Report(shallow=gitlog.is_shallow(repo))
    if report.shallow:
        if not limits.allow_shallow:
            raise gitlog.HistoryError(
                "shallow clone: history beyond the shallow boundary does not exist here, so a clean result "
                "would claim too much. Fetch full history (git fetch --unshallow) or pass --allow-shallow."
            )
        _say("history: WARNING shallow clone; commits beyond the shallow boundary were not scanned")
    in_range = gitlog.count_commits(repo, since)
    report.truncated = in_range > limits.max_commits
    report.commits = min(in_range, limits.max_commits)
    _say(f"history: listing up to {report.commits} of {in_range} commits")
    log = gitlog.touches(repo, since, limits.max_commits)
    report.skipped_submodules = log.submodules
    oids = sorted({t.oid for t in log.touches})
    _say(f"history: {len(log.touches)} changed paths, {len(oids)} distinct blobs")
    judged = _read_judged(repo, rules, oids, limits, report)
    report.findings = _collect(log.touches, rules, judged)
    _say(
        f"history: skipped {report.skipped_binary} binary, {report.skipped_oversize} oversize blobs "
        f"and {report.skipped_submodules} submodule pointers (not scanned)"
    )
    return report

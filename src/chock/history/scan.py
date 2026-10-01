"""Judge the blobs a repository's history introduced with the installed content gates."""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path

from chock.history import gitlog
from chock.history.gates import RULE_CONTENT, RULE_PATH, Rule

DEFAULT_MAX_COMMITS = 5000
DEFAULT_MAX_BLOB_BYTES = 1_048_576
_PROGRESS_EVERY = 500


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
    truncated: bool = False
    shallow: bool = False


@dataclass(frozen=True)
class Limits:
    max_commits: int = DEFAULT_MAX_COMMITS
    max_blob_bytes: int = DEFAULT_MAX_BLOB_BYTES


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _judge_blob(rules: list[Rule], data: bytes) -> tuple[list[tuple[int, int, str]], set[int]]:
    """(rule index, line number, line digest) per hit, and the rules whose waiver pragma the blob carries."""
    text = data.decode("utf-8", "replace")
    lines = text.split("\n")
    hits = [(i, n, _digest(lines[n - 1])) for i, rule in enumerate(rules) for n in rule.hits(text)]
    waived = {i for i, rule in enumerate(rules) if rule.pragma_re and rule.pragma_re.search(text)}
    return hits, waived


def _say(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def _read_judged(
    repo: Path, rules: list[Rule], oids: list[str], limits: Limits, report: Report
) -> dict[str, tuple[list[tuple[int, int, str]], set[int]]]:
    """Judge each distinct blob once: oversize and binary ones are skipped, never read whole into the verdict."""
    sizes = gitlog.blob_sizes(repo, oids)
    wanted = [o for o in oids if o in sizes and 0 < sizes[o] <= limits.max_blob_bytes]
    report.skipped_oversize = sum(1 for o in oids if sizes.get(o, 0) > limits.max_blob_bytes)
    judged: dict[str, tuple[list[tuple[int, int, str]], set[int]]] = {}
    for done, (oid, data) in enumerate(gitlog.read_blobs(repo, wanted), start=1):
        if gitlog.is_binary(data):
            report.skipped_binary += 1
        else:
            judged[oid] = _judge_blob(rules, data)
            report.blobs_scanned += 1
        if done % _PROGRESS_EVERY == 0:
            _say(f"history: read {done}/{len(wanted)} blobs")
    return judged


def _collect(
    touched: list[gitlog.Touch], rules: list[Rule], judged: dict[str, tuple[list[tuple[int, int, str]], set[int]]]
) -> list[Finding]:
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
            if not rule.covers(item.path):
                continue
            if rule.path_re and rule.path_re.search(item.path) and index not in waived:
                add(item, rule, RULE_PATH, None, RULE_PATH)
        for index, number, digest in hits:
            if rules[index].covers(item.path):
                add(item, rules[index], RULE_CONTENT, number, digest)
    return found


def scan(repo: Path, rules: list[Rule], since: str | None, limits: Limits) -> Report:
    report = Report(shallow=gitlog.is_shallow(repo))
    in_range = gitlog.count_commits(repo, since)
    report.truncated = in_range > limits.max_commits
    _say(f"history: listing up to {min(in_range, limits.max_commits)} of {in_range} commits")
    touched = gitlog.touches(repo, since, limits.max_commits)
    report.commits = min(in_range, limits.max_commits)
    oids = sorted({t.oid for t in touched})
    _say(f"history: {len(touched)} changed paths, {len(oids)} distinct blobs")
    judged = _read_judged(repo, rules, oids, limits, report)
    report.findings = _collect(touched, rules, judged)
    return report

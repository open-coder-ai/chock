"""`chock incident`: an ordered, redacted timeline from the local decision log, as evidence. Never sends anything."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from chock.gate.runner import chain as log_chain
from chock.gate.runner import journal
from chock.gatelog_chain import Chain, chains, walk
from chock.gatelog_read import HEARTBEAT_EVENT, ROUTES
from chock.incident_render import ALLOWED, RENDER
from chock.witness_export import LOCAL_ONLY, redact

FORMATS = ("text", "md", "json")
_STAMP = "%Y-%m-%dT%H:%M:%SZ"
_STAMPED = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_RELATIVE = re.compile(r"^(\d+)([mhd])$")
_UNITS = {"m": "minutes", "h": "hours", "d": "days"}
STOP_EVENTS = ("repo_stop", "repo_resume")
#: The fields an entry shows, in this order; every other field stays in the log.
SHOWN = (
    "route",
    "agent",
    "client",
    "actor",
    "session_id",
    "event",
    "policy_id",
    "verdict",
    "would_action",
    "override",
    "approver",
    "scope",
    "who",
    "target",
    "reason",
)
NO_SESSION = "-"
#: The place of a line no dated record sits beside: sorted first, shown as an unknown time.
UNDATED = ""
#: Breaks that are the line being unreadable: listed once, as unreadable.
_LISTED_AS_UNREADABLE = ("not-json", "unreadable")
_ORDER = "_order"


def parse_time(text: str) -> str:
    """`text` as a UTC second (`2026-10-14T09:30:00Z`): an ISO date or time (no zone means UTC), or `24h`/`90m`/`3d` ago."""
    relative = _RELATIVE.match(text.strip())
    if relative:
        ago = timedelta(**{_UNITS[relative[2]]: int(relative[1])})
        return (datetime.now(timezone.utc) - ago).strftime(_STAMP)
    moment = _moment(text)
    if moment is None:
        msg = f"{text!r} is not an ISO date or time, nor <N>m, <N>h or <N>d"
        raise argparse.ArgumentTypeError(msg)
    return moment


def _moment(value: object) -> str | None:
    """`value` as a UTC second, or None when it is no ISO date or time."""
    if isinstance(value, str) and _STAMPED.match(value):
        return value
    try:
        moment = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        moment = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).strftime(_STAMP)
    except (ValueError, OverflowError):  # not a time, or one past the calendar's edge in UTC
        return None


def kind_of(record: dict[str, Any]) -> str | None:
    """What a record is on the timeline; ALLOWED for a plain allowed call; None for a debug line it leaves out."""
    event = record.get("event")
    if event == HEARTBEAT_EVENT:
        return "session_start"
    if event in STOP_EVENTS and "verdict" not in record:
        return str(event)
    if "override" in record:
        return "override"
    if record.get("verdict") != journal.LOG_ALLOW or "would_action" in record:
        return "decision"
    if journal.log_plain_action(record) and not record.get("policy_id"):
        return ALLOWED
    return None


@dataclass
class Row:
    """One line of one log: where it is, its record or what is wrong with it, and the chain break it shows."""

    order: tuple[int, int]
    where: tuple[str, int]
    record: dict[str, Any] | None
    problem: str | None
    broken: dict[str, Any] | None
    ts: str | None = None


@dataclass
class Timeline:
    """What one window of the log holds: its entries in order, its sessions, and each log's chain within it."""

    since: str
    until: str | None
    share: bool
    logs: list[str] = field(default_factory=list)
    entries: list[dict[str, Any]] = field(default_factory=list)
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    chains: list[dict[str, Any]] = field(default_factory=list)
    omitted: int = 0

    def within(self, ts: str) -> bool:
        return ts == UNDATED or (ts >= self.since and (self.until is None or ts < self.until))


def _parse(line: bytes | None) -> tuple[dict[str, Any] | None, str | None]:
    """(the record, None), or (None, what is wrong with the line)."""
    if line is None:
        return None, "unreadable file"
    try:
        record = json.loads(line)
    except ValueError:
        return None, "not a JSON record"
    if not isinstance(record, dict):
        return None, "not a JSON object"
    if _moment(record.get("ts")) is None:
        return None, "no readable ts"
    return record, None


def _rows(index: int, chain: Chain) -> list[Row]:
    """Every line of `chain` in file order, each dated by its own ts, else by the nearest dated line before or after it."""
    rows = []
    for number, (where, line, broken) in enumerate(walk(chain)):
        record, problem = _parse(line)
        rows.append(Row((index, number), where, record, problem, broken, _moment(record["ts"]) if record else None))
    for ordered in (rows, rows[::-1]):
        near = None
        for row in ordered:
            row.ts = row.ts or near
            near = row.ts
    for row in rows:
        row.ts = row.ts or UNDATED
    return rows


def _entry(kind: str, row: Row, fields: dict[str, Any], place: int = 1) -> dict[str, Any]:
    """One timeline entry; `_order` (log, line, place) keeps equal times in log order, a break before its line."""
    return {"ts": row.ts, "kind": kind, "at": f"{row.where[0]}:{row.where[1]}", **fields, _ORDER: (*row.order, place)}


def _session(timeline: Timeline, row: Row, kind: str) -> None:
    """Count `row`'s record toward its session: when it ran, who acted, its allowed calls and its verdicts."""
    record = row.record or {}
    sid = str(record.get("session_id") or NO_SESSION)
    found = timeline.sessions.setdefault(sid, {"first": row.ts, "last": row.ts, "actors": set(), ALLOWED: 0})
    found["first"], found["last"] = min(found["first"], row.ts), max(found["last"], row.ts)
    if record.get("actor"):
        found["actors"].add(str(record["actor"]))
    if kind == ALLOWED:
        found[ALLOWED] += 1
    elif kind == "decision":
        found.setdefault("verdicts", Counter())[str(record.get("verdict") or "-")] += 1
    elif kind == "override":
        found["overrides"] = found.get("overrides", 0) + 1


def _record(timeline: Timeline, row: Row, seqs: list[int]) -> None:
    """Put one dated record on the timeline, count it, or leave it out (a debug line)."""
    record = row.record or {}
    seq = record.get(log_chain.LOG_CHAIN_SEQ)
    if log_chain.LOG_CHAIN_UNCHAINED not in record and type(seq) is int:
        seqs.append(seq)
    kind = kind_of(record)
    if kind is None:
        timeline.omitted += 1
        return
    _session(timeline, row, kind)
    if kind != ALLOWED:
        timeline.entries.append(_entry(kind, row, {k: record[k] for k in SHOWN if record.get(k) not in (None, "")}))


def _read_log(timeline: Timeline, index: int, label: str, files: list[Path]) -> None:
    """Add one log's lines in the window to `timeline`, and its chain line."""
    seqs: list[int] = []
    breaks: list[dict[str, Any]] = []
    outside = 0
    for row in _rows(index, Chain(label, files)):
        if not timeline.within(str(row.ts)):
            outside += row.broken is not None
            continue
        if row.broken:
            breaks.append(row.broken)
            if row.broken["kind"] not in _LISTED_AS_UNREADABLE:
                found = row.broken
                timeline.entries.append(
                    _entry(
                        "chain_break",
                        row,
                        {"break": found["kind"], "expected": found["expected"], "found": found["found"]},
                        0,
                    )
                )
        if row.problem:
            timeline.entries.append(_entry("unreadable", row, {"problem": row.problem}))
        else:
            _record(timeline, row, seqs)
    timeline.chains.append({"log": label, "seqs": seqs, "breaks": breaks, "outside": outside})


def build(repo_root: Path, since: str, until: str | None, *, route: str | None = None, share: bool = False) -> Timeline:
    """The window [since, until) of every decision log on the routes asked for, redacted, oldest first."""
    timeline = Timeline(since, until, share)
    for index, (label, files) in enumerate(chains(repo_root, route)):
        timeline.logs.append(label)
        _read_log(timeline, index, label, files)
    home = os.path.expanduser("~")
    hidden = (*LOCAL_ONLY, _ORDER) if share else (_ORDER,)
    entries = sorted(timeline.entries, key=lambda e: (e["ts"], e[_ORDER]))
    timeline.entries = [redact({k: v for k, v in e.items() if k not in hidden}, home) for e in entries]
    timeline.chains = redact(timeline.chains, home)
    timeline.sessions = redact(
        {sid: {**s, "actors": sorted(s["actors"])} for sid, s in timeline.sessions.items()}, home
    )
    return timeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chock incident", description=__doc__)
    parser.add_argument(
        "--since",
        required=True,
        type=parse_time,
        help="Start, included: ISO date/time (UTC if no zone) or 24h, 90m, 3d ago",
    )
    parser.add_argument("--until", type=parse_time, help="End, not included (default: now)")
    parser.add_argument("--format", choices=FORMATS, default="text")
    parser.add_argument("--share", action="store_true", help="Leave out approver and who (a person's git email)")
    parser.add_argument("--repo", default=".", help="Repository root whose sync-route log is read (default: cwd)")
    parser.add_argument("--route", choices=ROUTES)
    args = parser.parse_args(argv)
    if args.until is not None and args.until <= args.since:
        parser.error(f"--until {args.until} is not after --since {args.since}")
    timeline = build(Path(args.repo).resolve(), args.since, args.until, route=args.route, share=args.share)
    sys.stdout.write(RENDER[args.format](timeline))
    return 0

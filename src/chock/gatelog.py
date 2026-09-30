"""`chock status --only log` -- read the local gate outcome log."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from chock.gatelog_report import _printable, render_groups_md, render_groups_text

LOG_DIR = "log"
LOG_NAME = "gate-events.jsonl"
ROTATED_NAME = "gate-events.1.jsonl"

GROUP_KEYS = ("policy", "rule", "agent", "event")
FORMATS = ("text", "md")
UNKNOWN = "unknown"
TOP_FILES = 3
_SINCE_RANGE = "must be 1 or more days"
#: A gate's `matches` line is `<path>[:<line>]: <label>`; only the path is read, never the label.
_MATCH_PATH_RE = re.compile(r"^(?P<path>[^\s:]+)(?::\d+)?: ")


def log_files(repo_root: Path) -> list[Path]:
    """Current and rotated log files, oldest first, skipping any that are absent."""
    base = Path(repo_root) / ".chock" / LOG_DIR
    return [path for path in (base / ROTATED_NAME, base / LOG_NAME) if path.exists()]


def read_events(repo_root: Path, since_days: int | None = None) -> list[dict[str, Any]]:
    """Every readable record, oldest first."""
    cutoff = None
    if since_days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    events: list[dict[str, Any]] = []
    for path in log_files(repo_root):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict) or not record.get("policy_id"):
                continue
            if cutoff and str(record.get("ts", "")) < cutoff:
                continue
            events.append(record)
    return events


def summarize(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per (policy, surface) totals, most-active first."""
    totals: dict[tuple[str, str], dict[str, Any]] = {}
    for record in events:
        key = (str(record.get("policy_id")), str(record.get("surface") or "unknown"))
        entry = totals.setdefault(
            key,
            {
                "policy_id": key[0],
                "surface": key[1],
                "events": 0,
                "allow": 0,
                "block": 0,
                "ask": 0,
                "warn": 0,
                "last_block": None,
            },
        )
        entry["events"] += 1
        verdict = record.get("verdict")
        if verdict in ("ask", "warn"):
            entry[verdict] += 1
        elif verdict == "block":
            entry["block"] += 1
            ts = str(record.get("ts") or "")
            if ts > (entry["last_block"] or ""):
                entry["last_block"] = ts
        else:
            entry["allow"] += 1
    return sorted(totals.values(), key=lambda e: (-e["events"], e["policy_id"]))


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _group_names(record: dict[str, Any], by: str) -> list[str]:
    """The groups a record counts toward; a record lacking the field counts under "unknown"."""
    if by == "policy":
        return [str(record["policy_id"])]
    if by == "rule":
        rules = record.get("rules")
        return sorted(rules) if isinstance(rules, dict) and rules else [UNKNOWN]
    return [str(record.get(by) or UNKNOWN)]


def _record_files(record: dict[str, Any]) -> list[str]:
    matches = record.get("matches")
    found = (_MATCH_PATH_RE.match(m) for m in matches if isinstance(m, str)) if isinstance(matches, list) else ()
    return sorted({m.group("path") for m in found if m})


def _new_group(name: str) -> dict[str, Any]:
    return {
        "group": name,
        "events": 0,
        "allow": 0,
        "block": 0,
        "ask": 0,
        "warn": 0,
        "would_block": 0,
        "new_findings": 0,
        "baseline_findings": 0,
        "agents": set(),
        "rules": Counter(),
        "files": Counter(),
    }


def _tally(entry: dict[str, Any], record: dict[str, Any], by: str) -> None:
    """Add one record to a group. Grouped by rule, `new` is that rule's own count; the verdict,
    baseline and file columns stay per record, since the log does not tie them to one rule."""
    entry["events"] += 1
    verdict = record.get("verdict")
    entry[verdict if verdict in ("block", "ask", "warn") else "allow"] += 1
    entry["would_block"] += record.get("would_block") is True
    rules = record.get("rules")
    if by == "rule" and isinstance(rules, dict) and entry["group"] in rules:
        entry["new_findings"] += _count(rules[entry["group"]])
    else:
        entry["new_findings"] += _count(record.get("new_findings"))
    entry["baseline_findings"] += _count(record.get("baseline_findings"))
    if record.get("agent"):
        entry["agents"].add(str(record["agent"]))
    if by != "rule" and isinstance(rules, dict):
        entry["rules"].update({str(k): _count(v) for k, v in rules.items()})
    entry["files"].update(_record_files(record))


def group_events(events: list[dict[str, Any]], by: str) -> list[dict[str, Any]]:
    """Counts per `by` group (policy, rule, agent or event), most-intercepted first.

    Reads only verdicts, counts, ids and the paths in `matches`; a file's contents are never logged.
    """
    groups: dict[str, dict[str, Any]] = {}
    for record in events:
        for name in _group_names(record, by):
            _tally(groups.setdefault(name, _new_group(name)), record, by)
    rows = []
    for entry in groups.values():
        entry["agents"] = sorted(entry["agents"])
        entry["rules"] = dict(entry["rules"].most_common())
        top = sorted(entry["files"].items(), key=lambda item: (-item[1], item[0]))[:TOP_FILES]
        entry["files"] = [{"path": p, "count": n} for p, n in top]
        rows.append(entry)
    return sorted(rows, key=lambda e: (-(e["block"] + e["ask"] + e["warn"]), -e["events"], e["group"]))


def installed_policies(repo_root: Path) -> list[str]:
    """Policy ids present in the repo, from the directory tree rather than the registry."""
    root = Path(repo_root) / ".agents" / "policies"
    if not root.is_dir():
        return []
    return sorted(
        {path.parent.name for path in root.glob("*/manifest.yaml")}
        | {path.parent.name for path in root.glob("*/*/manifest.yaml")}
    )


def render_text(summary: list[dict[str, Any]], silent: list[str]) -> str:
    if not summary:
        lines = ["No gate outcomes recorded yet."]
    else:
        width = max(len(str(e["policy_id"])) for e in summary)
        lines = [
            f"{'policy'.ljust(width)}  {'surface':<13} {'events':>6} {'allow':>6} {'block':>6} {'ask':>4} {'warn':>5}  last block"
        ]
        for entry in summary:
            last = entry["last_block"] or "never"
            lines.append(
                f"{str(entry['policy_id']).ljust(width)}  {entry['surface']:<13} "
                f"{entry['events']:>6} {entry['allow']:>6} {entry['block']:>6} {entry['ask']:>4} {entry['warn']:>5}  {last}"
            )
    if silent:
        lines.append("")
        lines.append(f"Never recorded ({len(silent)}): {', '.join(silent)}")
        lines.append("Advisory policies emit no runtime event, so absence here is not evidence of a gap.")
    return "\n".join(lines)


def positive_days(value: str) -> int:
    """argparse type for `--since`: a whole number of days, 1 or more."""
    days = int(value)
    if days < 1:
        raise argparse.ArgumentTypeError(_SINCE_RANGE)
    return days


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chock status --only log", description="Read the gate outcome log")
    parser.add_argument("--repo", default=".", help="Repository root (default: cwd)")
    parser.add_argument("--policy", help="Restrict the report to one policy id")
    parser.add_argument("--since", type=positive_days, metavar="DAYS", help="Only records from the last N days")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable results")
    parser.add_argument("--by", choices=GROUP_KEYS, help="Group counts by policy, rule, agent or event")
    parser.add_argument("--format", choices=FORMATS, default="text", help="md prints a paste-able markdown summary")
    args = parser.parse_args(argv)
    if args.json and args.format == "md":
        parser.error("--json and --format md are mutually exclusive")

    repo_root = Path(args.repo).resolve()
    events = read_events(repo_root, args.since)
    if args.policy:
        events = [e for e in events if e.get("policy_id") == args.policy]

    by = args.by or ("policy" if args.format == "md" else None)
    if by:
        rows = group_events(events, by)
        if args.json:
            print(json.dumps({"by": by, "groups": rows, "events": len(events)}, indent=2))
        elif args.format == "md":
            print(render_groups_md(rows, by, args.since))
        else:
            print(_printable(render_groups_text(rows, by)))
        return 0

    summary = summarize(events)
    recorded = {str(e["policy_id"]) for e in summary}
    silent = [p for p in installed_policies(repo_root) if p not in recorded]
    if args.policy:
        silent = [p for p in silent if p == args.policy]

    if args.json:
        print(json.dumps({"summary": summary, "silent": silent, "events": len(events)}, indent=2))
    else:
        print(_printable(render_text(summary, silent)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

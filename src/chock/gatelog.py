"""`chock status --only log` -- read the local gate outcome log.

The log is written by two vendored runners (`gate/runner.py`, `gate/pretooluse.py`) and
answers one question policy authoring could not answer before: which enforcement actually
happens. Two findings come out of it, and the second is the one nobody expects.

  fired and blocked   -> the gate works, and the block rate says whether it over-fires
  never recorded      -> the policy has never been consulted at all

A policy that has never been consulted is not "passing". It is unenforced, and reporting it
alongside the ones that fire is the point of the `silent` section below.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

LOG_DIR = "log"
LOG_NAME = "gate-events.jsonl"
ROTATED_NAME = "gate-events.1.jsonl"


def log_files(repo_root: Path) -> list[Path]:
    """Current and rotated log files, oldest first, skipping any that are absent."""
    base = Path(repo_root) / ".chock" / LOG_DIR
    return [path for path in (base / ROTATED_NAME, base / LOG_NAME) if path.exists()]


def read_events(repo_root: Path, since_days: int | None = None) -> list[dict[str, Any]]:
    """Every readable record, oldest first.

    A malformed line is skipped rather than fatal. This file is appended to by git hooks
    running concurrently; a torn write is a lost record, not a reason to refuse to report.
    """
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
            # Timestamps are fixed-width UTC, so a string compare orders them correctly and
            # needs no parsing -- which also means one unparseable ts cannot drop a record.
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
            {"policy_id": key[0], "surface": key[1], "events": 0, "allow": 0, "block": 0, "last_block": None},
        )
        entry["events"] += 1
        if record.get("verdict") == "block":
            entry["block"] += 1
            ts = str(record.get("ts") or "")
            if ts > (entry["last_block"] or ""):
                entry["last_block"] = ts
        else:
            entry["allow"] += 1
    return sorted(totals.values(), key=lambda e: (-e["events"], e["policy_id"]))


def installed_policies(repo_root: Path) -> list[str]:
    """Policy ids present in the repo, from the directory tree rather than the registry.

    `_baseline` and other grouping directories hold policies one level down, so a nested
    manifest counts as its own policy. Reading the tree keeps this honest for a repo whose
    registry is stale, which is exactly the repo most likely to have unenforced policies.
    """
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
        lines = [f"{'policy'.ljust(width)}  {'surface':<13} {'events':>6} {'allow':>6} {'block':>6}  last block"]
        for entry in summary:
            last = entry["last_block"] or "never"
            lines.append(
                f"{str(entry['policy_id']).ljust(width)}  {entry['surface']:<13} "
                f"{entry['events']:>6} {entry['allow']:>6} {entry['block']:>6}  {last}"
            )
    if silent:
        # Named, not counted. "9 policies never fired" is a statistic; the list is a worklist.
        lines.append("")
        lines.append(f"Never recorded ({len(silent)}): {', '.join(silent)}")
        lines.append("Advisory policies emit no runtime event, so absence here is not evidence of a gap.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chock status --only log", description="Read the gate outcome log")
    parser.add_argument("--repo", default=".", help="Repository root (default: cwd)")
    parser.add_argument("--policy", help="Restrict the report to one policy id")
    parser.add_argument("--since", type=int, metavar="DAYS", help="Only records from the last N days")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable results")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    events = read_events(repo_root, args.since)
    if args.policy:
        events = [e for e in events if e.get("policy_id") == args.policy]

    summary = summarize(events)
    recorded = {str(e["policy_id"]) for e in summary}
    silent = [p for p in installed_policies(repo_root) if p not in recorded]
    if args.policy:
        silent = [p for p in silent if p == args.policy]

    if args.json:
        print(json.dumps({"summary": summary, "silent": silent, "events": len(events)}, indent=2))
    else:
        print(render_text(summary, silent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

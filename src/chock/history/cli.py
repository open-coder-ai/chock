"""`chock check --history`: scan the existing git history once, with the installed content gates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from chock.history import gitlog
from chock.history.gates import load_rules
from chock.history.scan import DEFAULT_MAX_BLOB_BYTES, DEFAULT_MAX_COMMITS, Limits, Report, scan

EXIT_FINDINGS = 1
EXIT_ERROR = 2
_SHORT = 12
_NOT_POSITIVE = "must be a positive integer"


def _positive(raw: str) -> int:
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError(_NOT_POSITIVE)
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chock check --history",
        description="Scan existing git history (read-only) with the installed content gates. "
        "Exit 1 when findings exist; --report-only exits 0.",
    )
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument("--since", default=None, help="Scan only commits after this rev (<rev>..HEAD)")
    parser.add_argument("--max-commits", type=_positive, default=DEFAULT_MAX_COMMITS, help="Newest commits to scan")
    parser.add_argument("--max-blob-bytes", type=_positive, default=DEFAULT_MAX_BLOB_BYTES, help="Skip larger blobs")
    parser.add_argument("--json", action="store_true", help="Machine-readable report on stdout")
    parser.add_argument(
        "--report-only", action="store_true", help="Report findings but exit 0 (history before adoption)"
    )
    return parser


def _plain(text: str) -> str:
    """`text` with every non-printable character shown as `?`: a path comes from the repository."""
    return "".join(ch if ch.isprintable() else "?" for ch in text)


def _document(report: Report, applied: list[str], skipped: list[str]) -> dict[str, object]:
    return {
        "commits_scanned": report.commits,
        "blobs_scanned": report.blobs_scanned,
        "skipped_binary": report.skipped_binary,
        "skipped_oversize": report.skipped_oversize,
        "truncated": report.truncated,
        "shallow": report.shallow,
        "gates_applied": applied,
        "gates_not_applied": skipped,
        "findings": [f.as_dict() for f in report.findings],
    }


def _text(report: Report, applied: list[str], skipped: list[str]) -> str:
    out = [
        f"history scan: {report.commits} commits, {report.blobs_scanned} distinct blobs "
        f"(skipped {report.skipped_binary} binary, {report.skipped_oversize} oversize)",
        f"gates applied: {', '.join(applied)}",
    ]
    if skipped:
        out.append(f"gates not applied to history (not a content pattern): {', '.join(skipped)}")
    if report.truncated:
        out.append("note: history truncated at --max-commits; older commits were not scanned")
    if report.shallow:
        out.append("note: shallow clone; commits beyond the shallow boundary were not scanned")
    for f in report.findings:
        where = _plain(f.path) + (f":{f.line}" if f.line else "")
        out.append(f"  {f.commit[:_SHORT]} {where}  [{f.policy}: {f.rule}]")
    if report.findings:
        out.append(
            f"{len(report.findings)} finding(s). Matched text is never printed. A committed secret stays valid "
            "until rotated; chock never rewrites history."
        )
    else:
        out.append("no findings")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo = Path(args.repo)
    try:
        since = gitlog.resolve_rev(repo, args.since) if args.since is not None else None
        if not gitlog.has_commits(repo):
            print("history: no commits to scan", file=sys.stderr)
            return 0
        rules, skipped = load_rules(repo)
        report = scan(repo, rules, since, Limits(args.max_commits, args.max_blob_bytes))
    except gitlog.HistoryError as exc:
        print(f"history: {exc}", file=sys.stderr)
        return EXIT_ERROR
    applied = sorted({r.policy for r in rules})
    if args.json:
        print(json.dumps(_document(report, applied, skipped), indent=2))
    else:
        print(_text(report, applied, skipped))
    return EXIT_FINDINGS if report.findings and not args.report_only else 0


def check_main(argv: list[str] | None) -> int:
    """`chock check`: `--history` runs the history scan, anything else the usual truth checks."""
    args = list(argv or [])
    if "--history" in args:
        return main([a for a in args if a != "--history"])
    from chock.lifecycle import check_main as truth_checks

    return truth_checks(argv)

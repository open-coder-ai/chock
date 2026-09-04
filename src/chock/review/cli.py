"""`chock review` -- produce and check reviewer evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from chock.emit import write_generated
from chock.output import error
from chock.review.evidence import (
    EVIDENCE_DIR,
    EvidenceError,
    build,
    check_registry,
    load,
    require,
    required_checks,
    verify,
)

DEFAULT_BASE = "origin/main"


def _emit(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    registry = sorted(check_registry(root))
    checks = args.checks or registry
    evidence = build(root, args.base, {"kind": args.kind, "id": args.by}, checks, allow_empty=args.allow_empty)

    dest = Path(args.out) if args.out else root / EVIDENCE_DIR / f"{evidence['diff_sha'][:12]}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_generated(dest, json.dumps(evidence, indent=2) + "\n")

    failed = [e["check"] for e in evidence["verified"] if e["result"] == "fail"]
    print(f"Wrote {dest.relative_to(root) if dest.is_relative_to(root) else dest}")
    print(f"  diff {evidence['diff_sha'][:12]} against {args.base}")
    print(
        f"  verified: {len(evidence['verified'])} check(s)"
        + (f", {len(failed)} failing: {', '.join(failed)}" if failed else "")
    )
    print("  attested: 0 -- a machine cannot attest. Add judgement claims before requesting review.")
    narrowed = sorted(set(registry) - set(checks))
    if narrowed:
        print(
            f"  WARNING: {len(narrowed)} registered check(s) not run: {', '.join(narrowed)}. "
            "`review verify` rejects evidence that does not cover the registry."
        )
    return 1 if failed else 0


def _verify(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    evidence = load(Path(args.file))
    failures = verify(root, evidence, args.base)

    attested = evidence.get("attested") or []
    if failures:
        print(f"Evidence does not hold ({len(failures)} problem(s)):", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    who = evidence.get("produced_by", {})
    registry = sorted(check_registry(root))
    named = {e.get("check") for e in evidence.get("verified") or []}
    print(f"Evidence holds: {len(evidence.get('verified') or [])} check(s) re-derived and matching.")
    uncovered = sorted(set(registry) - named)
    required = required_checks(root)
    scope = "required set" if required else "registry"
    print(
        f"  coverage: {len(named & set(registry))} of {len(registry)} registered check(s)"
        + (f" -- NOT covered: {', '.join(uncovered)}" if uncovered else "")
    )
    if uncovered and not required:
        print(
            f"  this repository declares no `required_checks`, so the {scope} is not enforced; "
            "an author chose which checks to run."
        )
    print(f"  produced by {who.get('kind', '?')} {who.get('id', '?')}")
    if attested:
        print(f"  {len(attested)} attestation(s), NOT verified -- a human decides whether to believe them:")
        for item in attested:
            confidence = f" [{item['confidence']}]" if item.get("confidence") else ""
            print(f"    ({item.get('criterion', '?')}){confidence} {item.get('claim', '')}")
            print(f"      basis: {item.get('basis', '')}")
    else:
        print("  0 attestations. Every criterion needing judgement is unaddressed.")
    return 0


def _require(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    failures = require(root, args.base)
    if failures:
        print(f"PR is not merge-ready ({len(failures)} problem(s)):", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"PR is merge-ready: evidence present, valid, sufficient, passing, and attested against {args.base}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chock review", description="Produce and check reviewer evidence")
    sub = parser.add_subparsers(dest="action", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=".", help="Repo root")
    common.add_argument("--base", default=DEFAULT_BASE, help=f"Base ref to diff against (default: {DEFAULT_BASE})")

    emit = sub.add_parser("emit", parents=[common], help="Run the checks and write evidence")
    emit.add_argument("--checks", nargs="*", default=None, help="Registry keys to run (default: all built-ins)")
    emit.add_argument("--kind", choices=["agent", "human"], default="agent")
    emit.add_argument("--by", default="unknown", help="Who is producing this")
    emit.add_argument("--out", default=None, help="Write here instead of .chock/evidence/")
    emit.add_argument(
        "--allow-empty", action="store_true", help="Record evidence even when the diff against --base is empty"
    )
    emit.set_defaults(fn=_emit)

    check = sub.add_parser("verify", parents=[common], help="Re-derive every verified claim")
    check.add_argument("file", help="Evidence JSON to check")
    check.set_defaults(fn=_verify)

    req = sub.add_parser("require", parents=[common], help="CI gate: is this PR merge-ready?")
    req.set_defaults(fn=_require)

    args = parser.parse_args(argv)
    try:
        return int(args.fn(args))
    except EvidenceError as exc:
        error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

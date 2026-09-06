"""`chock check --only evals` -- run a policy's eval suite."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chock.eval import context_report
from chock.eval.derive import derive_cases
from chock.eval.execute import run_case
from chock.eval.model import PolicyResult
from chock.eval.report import render_json, render_text
from chock.eval.suites import Policy, discover_policies

_REPO_HELP = "Repository root (default: cwd)"


def run_deterministic(policy: Policy, repo_root: Path) -> PolicyResult:
    result = PolicyResult(policy.id, "deterministic")
    if not policy.deterministic:
        for case in policy.cases():
            result.results.append(run_case(case, policy.dir, repo_root, policy.guards))
        return result

    for case in [*policy.cases(), *derive_cases(policy.id, policy.gate)]:
        result.results.append(run_case(case, policy.dir, repo_root, policy.guards))
    return result


def export_main(argv: list[str] | None = None) -> int:
    """`chock eval export` -- write tier-3 cases as a context-report run/v0.1 directory.

    A dedicated subcommand (not a `chock eval --only ...` flag): `eval` is a leaf command whose
    sole positional is `policy_id`, not a verb group like `plugin`/`review`, so the least
    disruptive way to add a second verb is to recognise the literal first token here rather than
    reshape the existing, tested `chock eval [policy_id]` invocation.
    """
    parser = argparse.ArgumentParser(
        prog="chock eval export", description="Export tier-3 policy evals to context-report's run/v0.1 format"
    )
    parser.add_argument("policy_id", nargs="*", help="Policy id(s) to export. Default: every policy in the repo.")
    parser.add_argument("--format", required=True, choices=["context-report"], help="Export format")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--repo", default=".", help=_REPO_HELP)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    out_dir = Path(args.out).resolve()
    result = context_report.export(repo_root, out_dir, args.policy_id or None)

    for notice in result.skipped:
        print(notice)
    for problem in result.errors:
        print(f"error: {problem}", file=sys.stderr)
    plural = "y" if len(result.exported) == 1 else "ies"
    print(f"Exported {len(result.exported)} polic{plural} to {out_dir}")
    return 2 if result.errors else 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["export"]:
        return export_main(argv[1:])

    parser = argparse.ArgumentParser(prog="chock check --only evals", description="Run policy eval suites")
    parser.add_argument("policy_id", nargs="?", help="Policy to evaluate. Default: every policy in the repo.")
    parser.add_argument("--repo", default=".", help=_REPO_HELP)
    parser.add_argument("--mode", choices=["deterministic", "agent"], default="deterministic")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable results")
    parser.add_argument("--verbose", action="store_true", help="Include skipped cases in the table")
    args = parser.parse_args(argv)

    if args.mode == "agent":
        print(
            "agent mode is not implemented. It needs a disposable sandbox, a budget cap, and "
            "an agent adapter. Deterministic mode replays every case that has an executable form.",
            file=sys.stderr,
        )
        return 2

    repo_root = Path(args.repo).resolve()
    policies = discover_policies(repo_root, args.policy_id)
    if not policies:
        target = f"policy {args.policy_id!r}" if args.policy_id else "policies"
        print(f"No {target} found under {repo_root}.", file=sys.stderr)
        return 2

    results = [run_deterministic(policy, repo_root) for policy in policies]
    print(render_json(results) if args.json else render_text(results, verbose=args.verbose))
    return 1 if any(r.blocking for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())

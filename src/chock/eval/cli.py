"""`chock check --only evals` -- run a policy's eval suite."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chock.eval.derive import derive_cases
from chock.eval.execute import run_case
from chock.eval.model import PolicyResult
from chock.eval.report import render_json, render_text
from chock.eval.suites import Policy, discover_policies


def run_deterministic(policy: Policy, repo_root: Path) -> PolicyResult:
    result = PolicyResult(policy.id, "deterministic")
    if not policy.deterministic:
        for case in policy.cases():
            result.results.append(run_case(case, policy.dir, repo_root, policy.guards))
        return result

    for case in [*policy.cases(), *derive_cases(policy.id, policy.gate)]:
        result.results.append(run_case(case, policy.dir, repo_root, policy.guards))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chock check --only evals", description="Run policy eval suites")
    parser.add_argument("policy_id", nargs="?", help="Policy to evaluate. Default: every policy in the repo.")
    parser.add_argument("--repo", default=".", help="Repository root (default: cwd)")
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

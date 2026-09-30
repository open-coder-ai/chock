"""Umbrella lifecycle commands: sync, check, status."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TextIO

from chock.gatelog import FORMATS, GROUP_KEYS, positive_days


def _run(label: str, fn, argv: list[str]) -> int:
    print(f"== {label}")
    return int(fn(argv) or 0)


def sync_main(argv: list[str] | None) -> int:
    """Recompile + rewire so the repo matches its declared policies (uv-sync semantics)."""
    parser = argparse.ArgumentParser(prog="chock sync")
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument("--agents", nargs="*", default=None, help="Comma- or space-separated target agents")
    parser.add_argument("--skip-hooks", action="store_true", help="Skip reinstalling git hooks")
    parser.add_argument("--check", action="store_true", help="Report drift and exit non-zero; write nothing")
    parser.add_argument("--ci", action="store_true", help="Also install the GitHub Actions CI gate workflow")
    parser.add_argument("--skills", action="store_true", help="Also install bundled authoring skills")
    args = parser.parse_args(argv)

    from chock.toggles import recompile_main

    passthrough = ["--repo", args.repo]
    if args.agents is not None:
        passthrough += ["--agents", *args.agents]
    if args.skip_hooks:
        passthrough.append("--skip-hooks")
    if args.check:
        passthrough.append("--check")
    rc = int(recompile_main(passthrough) or 0)
    if rc or args.check:
        return rc

    from chock.hooks.launch import record_interpreter

    # The launcher every agent hook runs prefers this interpreter; local config, never committed.
    record_interpreter(Path(args.repo))

    if args.ci:
        from chock.scaffold.install_ci import main as install_ci_main

        rc = max(rc, _run("install ci workflow", install_ci_main, [args.repo]))
    if args.skills:
        from chock.scaffold.skills import main as install_skills_main

        rc = max(rc, _run("install authoring skills", install_skills_main, [args.repo]))
    return rc


CHECKS = ("validate", "verify", "evals", "matrix", "mechanisms", "index", "conflicts", "baseline")


def _run_validate(args: argparse.Namespace) -> int:
    from chock.validation.engine import main as validate_main

    validate_argv = [args.repo]
    if args.mode:
        validate_argv += ["--mode", args.mode]
    if args.event:
        validate_argv += ["--event", args.event]
    return _run("validate", validate_main, validate_argv)


def _run_matrix(args: argparse.Namespace) -> int:
    from chock.validation.checks_matrix_mechanisms import MATRIX_RELATIVE_PATH

    matrix_file = Path(args.repo) / MATRIX_RELATIVE_PATH
    if not matrix_file.exists() and not args.only:
        print(f"== enforcement matrix (skipped: no {MATRIX_RELATIVE_PATH.as_posix()} in this repo)")
        return 0
    from chock.authoring.matrix import main as matrix_main

    return _run("enforcement matrix", matrix_main, [])


def _run_mechanisms(args: argparse.Namespace) -> int:
    from chock.validation.checks_matrix_mechanisms import MATRIX_RELATIVE_PATH
    from chock.validation.checks_matrix_mechanisms import main as mechanisms_main

    matrix_file = Path(args.repo) / MATRIX_RELATIVE_PATH
    if not matrix_file.exists() and not args.only:
        print(f"== matrix mechanisms (skipped: no {MATRIX_RELATIVE_PATH.as_posix()} in this repo)")
        return 0

    return _run("matrix mechanisms", mechanisms_main, ["--repo", args.repo])


def check_main(argv: list[str] | None) -> int:
    """Run every truth check: validate, verify, evals, matrix, index freshness, conflicts."""
    parser = argparse.ArgumentParser(prog="chock check")
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument("--only", default=None, help=f"Comma-separated subset of: {', '.join(CHECKS)}")
    parser.add_argument("--mode", default=None, help="Validation mode (passed to validate, e.g. frontier-claude)")
    parser.add_argument("--event", default=None, help="Hook event context (passed to validate, e.g. commit)")
    parser.add_argument("--base", default=None, help="Git ref the policy set may not be weaker than (baseline)")
    args = parser.parse_args(argv)

    selected = [s.strip() for s in args.only.split(",")] if args.only else list(CHECKS)
    unknown = sorted(set(selected) - set(CHECKS))
    if unknown:
        print(f"Unknown check(s): {', '.join(unknown)}. Choose from: {', '.join(CHECKS)}", file=sys.stderr)
        return 2

    rc = 0
    if "validate" in selected:
        rc = max(rc, _run_validate(args))
    if "verify" in selected:
        from chock.lock import main as verify_main

        rc = max(rc, _run("verify lockfile", verify_main, ["--repo", args.repo]))
    if "evals" in selected:
        from chock.eval.cli import main as eval_main

        rc = max(rc, _run("policy evals", eval_main, ["--repo", args.repo]))
    if "matrix" in selected:
        rc = max(rc, _run_matrix(args))
    if "mechanisms" in selected:
        rc = max(rc, _run_mechanisms(args))
    if "index" in selected:
        from chock.index.cli import cmd_refresh

        rc = max(rc, _run("index freshness", cmd_refresh, ["--repo", args.repo, "--check"]))
    if "conflicts" in selected:
        from chock.validation.checks_conflicts import main as conflicts_main

        rc = max(rc, _run("ambient conflicts", conflicts_main, ["--repo", args.repo]))
    if "baseline" in selected:
        rc = max(rc, _run_baseline(args))
    return rc


def _run_baseline(args: argparse.Namespace) -> int:
    from chock.validation.checks_baseline import main as baseline_main

    if not args.base:
        if args.only:
            print("baseline needs --base <ref>: the branch whose policy set this one may not weaken", file=sys.stderr)
            return 2
        print("== policy baseline (skipped: no --base given; CI passes the pull request's base branch)")
        return 0
    return _run("policy baseline", baseline_main, ["--repo", args.repo, "--base", args.base])


def _log_args(args: argparse.Namespace) -> list[str]:
    """The `status` flags that belong to the gate log, in `chock.gatelog`'s own spelling."""
    flags = [("--policy", args.policy), ("--since", args.since), ("--by", args.by), ("--format", args.format)]
    given = [part for flag, value in flags if value is not None for part in (flag, str(value))]
    return given + (["--json"] if args.json else [])


def _print_rollout(repo: Path, stream: TextIO = sys.stdout) -> None:
    """Lead with a level below enforce, where it came from, and what it does not reach."""
    from chock.gate.runner import ROLLOUT_ENFORCE, ROLLOUT_ENV, agent_signal, rollout

    signal = agent_signal(repo)
    level = rollout(repo, "pre-commit", signal)
    if level == ROLLOUT_ENFORCE:
        return
    from_env = signal is None and os.environ.get(ROLLOUT_ENV, "").strip() == level
    source = f"{ROLLOUT_ENV}={level} in this shell" if from_env else "`rollout:` in .chock/config.yaml"
    ceiling = "warn" if level == "observe" else "ask (and an ask does not fail CI)"
    print(
        f"ROLLOUT: {level}, from {source} -- compiled gates {ceiling} instead of blocking and record what "
        "enforce would have stopped (`chock status --only log`); command guards, tool_call gates and the "
        "MCP gateway still block. Remove it to enforce.",
        file=stream,
    )


def status_main(argv: list[str] | None) -> int:
    """Read-only picture of the repo: policy table, plus registry and gate log on request."""
    parser = argparse.ArgumentParser(prog="chock status")
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument("--only", default=None, help="Comma-separated subset of: policies, registry, log")
    log_flags = parser.add_argument_group("log section")
    log_flags.add_argument("--policy", help="Log: restrict to one policy id")
    log_flags.add_argument("--since", type=positive_days, metavar="DAYS", help="Log: only records from the last N days")
    log_flags.add_argument("--json", action="store_true", help="Log: machine-readable output")
    log_flags.add_argument("--by", choices=GROUP_KEYS, help="Log: group by policy, rule, agent or event")
    log_flags.add_argument("--format", choices=FORMATS, help="Log: md prints a markdown summary")
    args = parser.parse_args(argv)

    sections = ("policies", "registry", "log")
    selected = [s.strip() for s in args.only.split(",")] if args.only else ["policies"]
    unknown = sorted(set(selected) - set(sections))
    if unknown:
        print(f"Unknown section(s): {', '.join(unknown)}. Choose from: {', '.join(sections)}", file=sys.stderr)
        return 2

    if "log" not in selected and _log_args(args):
        print("--policy, --since, --json, --by and --format apply to `--only log`", file=sys.stderr)
        return 2

    if (args.json or args.format == "md") and selected != ["log"]:
        print("--json and --format md print the log alone: use `--only log`", file=sys.stderr)
        return 2

    # Machine output stays parseable: the level notice goes to stderr beside it.
    _print_rollout(Path(args.repo).resolve(), sys.stderr if args.json or args.format == "md" else sys.stdout)

    rc = 0
    if "policies" in selected:
        from chock.toggles import policies_main

        rc = max(rc, int(policies_main(["--repo", args.repo]) or 0))
    if "registry" in selected:
        from chock.registry.cli import main as registry_main

        rc = max(rc, _run("registry", registry_main, ["list", "--repo", args.repo]))
    if "log" in selected:
        from chock.gatelog import main as gatelog_main

        log_argv = ["--repo", args.repo, *_log_args(args)]
        if args.json or args.format == "md":
            rc = max(rc, int(gatelog_main(log_argv) or 0))
        else:
            rc = max(rc, _run("gate log", gatelog_main, log_argv))
    return rc

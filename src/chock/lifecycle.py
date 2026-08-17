"""Umbrella lifecycle commands: sync, check, status.

The adopter surface follows the verbs the Python toolchain already taught people
(`uv init/add/sync`, `poetry check`, `git status`). Each umbrella translates one
`--repo` flag into the per-tool conventions of the commands it wraps; the wrapped
entrypoints stay importable and are still exposed as hidden aliases for one
pre-launch cycle.
"""

from __future__ import annotations

import argparse
import sys


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

    if args.ci:
        from chock.scaffold.install_ci import main as install_ci_main

        rc = max(rc, _run("install ci workflow", install_ci_main, [args.repo]))
    if args.skills:
        from chock.scaffold.skills import main as install_skills_main

        rc = max(rc, _run("install authoring skills", install_skills_main, [args.repo]))
    return rc


# Matrix reads the cwd by design, which is why it ignores --repo; `chock check`
# documents that it must run from the repo root, exactly as CI already does. Every
# member is read-only: `check` never regenerates what it measures.
CHECKS = ("validate", "verify", "evals", "matrix", "index")


def check_main(argv: list[str] | None) -> int:
    """Run every truth check: validate, verify, evals, matrix, index freshness."""
    parser = argparse.ArgumentParser(prog="chock check")
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument("--only", default=None, help=f"Comma-separated subset of: {', '.join(CHECKS)}")
    parser.add_argument("--mode", default=None, help="Validation mode (passed to validate, e.g. frontier-claude)")
    parser.add_argument("--event", default=None, help="Hook event context (passed to validate, e.g. commit)")
    args = parser.parse_args(argv)

    selected = [s.strip() for s in args.only.split(",")] if args.only else list(CHECKS)
    unknown = sorted(set(selected) - set(CHECKS))
    if unknown:
        print(f"Unknown check(s): {', '.join(unknown)}. Choose from: {', '.join(CHECKS)}", file=sys.stderr)
        return 2

    rc = 0
    if "validate" in selected:
        from chock.validation.engine import main as validate_main

        validate_argv = [args.repo]
        if args.mode:
            validate_argv += ["--mode", args.mode]
        if args.event:
            validate_argv += ["--event", args.event]
        rc = max(rc, _run("validate", validate_main, validate_argv))
    if "verify" in selected:
        from chock.lock import main as verify_main

        rc = max(rc, _run("verify lockfile", verify_main, ["--repo", args.repo]))
    if "evals" in selected:
        from chock.eval.cli import main as eval_main

        rc = max(rc, _run("policy evals", eval_main, ["--repo", args.repo]))
    if "matrix" in selected:
        from pathlib import Path

        # The enforcement matrix is a framework-authoring artifact (spec/). Adopter
        # repos have no spec/ tree, and the default `chock check` must not fail them
        # for lacking one -- that is this framework's homework, not theirs. Asking for
        # it explicitly (--only matrix) still fails loudly when it is missing.
        matrix_file = Path(args.repo) / "spec" / "enforcement-matrix.md"
        if matrix_file.exists() or args.only:
            from chock.authoring.matrix import main as matrix_main

            rc = max(rc, _run("enforcement matrix", matrix_main, []))
        else:
            print("== enforcement matrix (skipped: no spec/enforcement-matrix.md in this repo)")
    if "index" in selected:
        from chock.index.cli import cmd_refresh

        rc = max(rc, _run("index freshness", cmd_refresh, ["--repo", args.repo, "--check"]))
    return rc


def status_main(argv: list[str] | None) -> int:
    """Read-only picture of the repo: policy table, plus registry and gate log on request."""
    parser = argparse.ArgumentParser(prog="chock status")
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument("--only", default=None, help="Comma-separated subset of: policies, registry, log")
    args = parser.parse_args(argv)

    sections = ("policies", "registry", "log")
    selected = [s.strip() for s in args.only.split(",")] if args.only else ["policies"]
    unknown = sorted(set(selected) - set(sections))
    if unknown:
        print(f"Unknown section(s): {', '.join(unknown)}. Choose from: {', '.join(sections)}", file=sys.stderr)
        return 2

    rc = 0
    if "policies" in selected:
        from chock.toggles import policies_main

        rc = max(rc, int(policies_main(["--repo", args.repo]) or 0))
    if "registry" in selected:
        from chock.registry.cli import main as registry_main

        rc = max(rc, _run("registry", registry_main, ["list", "--repo", args.repo]))
    if "log" in selected:
        from chock.gatelog import main as gatelog_main

        rc = max(rc, _run("gate log", gatelog_main, ["--repo", args.repo]))
    return rc

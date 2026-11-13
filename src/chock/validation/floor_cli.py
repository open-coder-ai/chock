"""`chock check --floor`'s flags on the check parser, and its dispatch from `chock check`."""

from __future__ import annotations

import argparse

from chock.validation.checks_floor import main


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--floor",
        action="store_true",
        help="Preview: judge base..head (base an ancestor of head: pass the merge result) with the base's gates, "
        "run by this engine; a changed guardrail path is listed and, by default, refused (needs --base; runs alone). "
        "It holds only as a required check the pull request cannot redefine (your setting, unverified by chock) and "
        "judges committed content only; under `listed` you rely on code-owner review of the listed paths. The list is "
        "what chock knows about, not a proof of completeness (a file your workflow installs chock from belongs on it: "
        "floor.control_plane_paths.add); a renamed or moved test file reads as a deletion and is refused",
    )
    parser.add_argument("--head", default=None, help="With --floor: the merge result under test (default HEAD)")


def from_check(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """The floor runs alone: every other check reads, and the evals run, the head's own files."""
    if not args.floor:
        parser.error("--head goes with --floor")
    sarif = args.format == "sarif"
    if not args.base or args.only or args.mode or args.event or bool(args.output) != sarif:
        parser.error("--floor needs --base, takes --format sarif only with --output, and no --only, --mode or --event")
    argv = ["--repo", args.repo, "--base", args.base, "--head", args.head or "HEAD"]
    argv += ["--head-ref", args.head_ref] if args.head_ref else []
    return main(argv + (["--sarif", args.output] if sarif else []))

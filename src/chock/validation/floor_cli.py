"""`chock check --floor`'s flags on the check parser, and its dispatch from `chock check`."""

from __future__ import annotations

import argparse

from chock.validation.checks_floor import main


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--floor",
        action="store_true",
        help="Judge base...head with the base's gates, waivers and tamper rules, run by this engine; "
        "no head file executes (needs --base; runs alone)",
    )
    parser.add_argument("--head", default=None, help="With --floor: the commit under test (default HEAD)")


def from_check(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """The floor runs alone: every other check reads, and the evals run, the head's own files."""
    if not args.floor:
        parser.error("--head goes with --floor")
    if not args.base or args.only or args.mode or args.event or args.format != "text" or args.output:
        parser.error("--floor needs --base and takes no --only, --mode, --event, --format or --output")
    argv = ["--repo", args.repo, "--base", args.base, "--head", args.head or "HEAD"]
    return main(argv + (["--head-ref", args.head_ref] if args.head_ref else []))

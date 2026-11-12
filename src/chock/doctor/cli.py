"""`chock doctor [--client X] [--repo .] [--live]`: each client's hooks on each route, PASS/WARN/FAIL with a fix."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from chock.display import inert
from chock.doctor import checks, live
from chock.doctor.targets import plugin_targets, sync_targets
from chock.stop_everywhere import everywhere_line


def _say(line: str) -> None:
    sys.stdout.write(inert(line) + "\n")


_LIVE_HELP = (
    "also run each installed pre-tool hook command, exactly as the client's config file writes it, from the repo: "
    "once on the first refusing eval case of the first policy it runs (it must refuse) and once on "
    f"`{live.HARMLESS}` (it must allow). It runs nothing else, starts no client, sends nothing anywhere and "
    "logs nothing. It does not prove the client calls the hook: that is the heartbeat row"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chock doctor", description=__doc__)
    parser.add_argument("--repo", default=".", help="the repository whose `chock sync` hooks to check")
    parser.add_argument("--client", help="one client: an install client id (claude-code) or agent id (claude_code)")
    parser.add_argument("--client-version", help="the client's version, compared with what agentseam witnessed")
    parser.add_argument("--sessions", type=int, default=checks.SESSIONS, help="sessions the heartbeat check covers")
    parser.add_argument("--json", action="store_true", help="one JSON object per target")
    parser.add_argument("--live", action="store_true", help=_LIVE_HELP)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo = Path(args.repo).resolve()
    stopped = everywhere_line()
    if stopped:
        (sys.stderr if args.json else sys.stdout).write(inert(stopped) + "\n")
    targets = [t for t in (*sync_targets(repo), *plugin_targets()) if args.client in (None, t.client, t.agent)]
    if not targets:
        who = f" for {args.client}" if args.client else ""
        _say(f"FAIL  no chock hooks found{who} in {repo} or a client's plugin folder")
        _say("      fix: run `chock sync --repo .` or `chock install --selection <file>`")
        return 1
    failed = False
    for target in targets:
        found = checks.run(target, repo, max(1, args.sessions), args.client_version)
        if args.live:
            found += live.run(target, repo)
        failed = failed or any(c.status == checks.FAIL for c in found)
        if args.json:
            row = {"client": target.client, "agent": target.agent, "route": target.route, "root": str(target.root)}
            _say(json.dumps({**row, "checks": [asdict(c) for c in found]}))
            continue
        _say(f"{target.client} [{target.route}] {target.root}")
        for check in found:
            _say(f"  {check.status:4}  {check.name}: {check.detail}")
            if check.fix and check.status != checks.PASS:
                _say(f"        fix: {check.fix}")
    return 1 if failed else 0

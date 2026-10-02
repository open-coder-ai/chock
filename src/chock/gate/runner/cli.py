"""Gate runner: the `gate.py` command line (`run` and `script-verdict`)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .constants import _GIT_EVENTS, AGENT_EVENTS, EXIT_ASK, EXIT_WARN
from .context import _GIT
from .verdict import run, script_verdict


# >>> gate.py 20
def _repo_root() -> Path:
    try:
        out = subprocess.check_output(  # noqa: S603 -- finding the repo root via git is this fallback's job
            [_GIT, "rev-parse", "--show-toplevel"], text=True, encoding="utf-8", errors="replace"
        )
        return Path(out.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, UnicodeError):
        return Path.cwd()


def _texts(raw: str, key: str) -> dict[str, str]:
    """One {path: text} map off the stdin payload. Unreadable input yields none, never a guess."""
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    texts = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(texts, dict):
        return {}
    return {str(path): str(text) for path, text in texts.items() if isinstance(text, str)}


def _session(raw: str) -> dict | None:
    """The session-log handle the hook handler put on stdin, if any."""
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return None
    session = payload.get("session") if isinstance(payload, dict) else None
    return session if isinstance(session, dict) else None


def _writes(raw: str) -> dict[str, str]:
    """The files this event puts under judgement, whole."""
    return _texts(raw, "writes")


def _utf8_streams() -> None:
    """Speak UTF-8 on stdin and stderr whatever the console code page, so a match cannot crash the verdict."""
    for stream in (sys.stdin, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _utf8_streams()
    parser = argparse.ArgumentParser(prog="gate.py")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="Run a compiled gate")
    run_p.add_argument("--gate", required=True, help="Path to compiled gate.json")
    run_p.add_argument("--event", required=True, choices=["pre-commit", "pre-push", "ci", *AGENT_EVENTS])
    run_p.add_argument("--base", help="Base ref to diff HEAD against (required for --event ci)")
    run_p.add_argument("--head-ref", help="Branch under test, e.g. $GITHUB_HEAD_REF (used by forbidden_ref)")
    verdict_p = sub.add_parser("script-verdict", help="Settle a script-backed git hook's exit 3 (ask) or 4 (warn)")
    verdict_p.add_argument("--policy", required=True, help="Policy id the script belongs to")
    verdict_p.add_argument("--event", required=True, choices=_GIT_EVENTS)
    verdict_p.add_argument("--exit", required=True, type=int, choices=[EXIT_ASK, EXIT_WARN], dest="code")
    args = parser.parse_args(argv)

    if args.command == "script-verdict":
        return script_verdict(args.policy, args.event, args.code, _repo_root())

    if args.event == "ci" and not args.base:
        parser.error("--event ci requires --base")

    if args.event in AGENT_EVENTS:
        # The files are on stdin because a tool call's content is not in the repository yet and
        # cannot be read back from it. {"writes": {"<path>": "<text>"}, "added": {"<path>": "<text>"}},
        # `added` present only for an edit, carrying the text it introduces.
        # Paths are named from the directory the runtime works in, which may sit below the git top-level.
        raw = sys.stdin.read()
        return run(
            Path(args.gate),
            args.event,
            None,
            Path.cwd(),
            writes=_writes(raw),
            added=_texts(raw, "added"),
            session=_session(raw),
        )

    push_stdin = sys.stdin.read() if args.event == "pre-push" and not sys.stdin.isatty() else None
    return run(Path(args.gate), args.event, push_stdin, _repo_root(), base=args.base, head_ref=args.head_ref)


if __name__ == "__main__":
    raise SystemExit(main())

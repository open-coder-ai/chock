#!/bin/sh
# fmt: off
"exec" "$(command -v python3 || command -v python)" "$0" "$@"
# fmt: on
# Refuse `git commit` and `gh pr create|edit` whose message or PR body narrates the development process.
# Scans inline text (-m/--message, -b/--body, clusters like -am), a readable -F/--file/--body-file, and a heredoc on `-F -`.
# Best effort: a deny-list of process-leak markers, deliberately narrow so a false block stays rare -- edit MARKERS to
# fit your team's vocabulary. The gh slice covers the CLI only; the CI backstop scans the PR body on the pull_request event.

import os
import re
import shlex
import sys
from pathlib import Path

from chock_shellparse import Cmd, commands, git_parts

# Phrases that describe the conversation rather than the change, matched case-insensitively as substrings. The
# session-URL marker is the concrete leak this policy was hardened for: agent harnesses append a claude.ai/code/session
# link to PR bodies, publishing a private session identifier on a public repo forever.
MARKERS = (
    "claude.ai/code/session",
    "user asked",
    "user asks",
    "user requested",
    "user said",
    "user wants",
    "the user's",
    "per the conversation",
    "per our conversation",
    "this conversation",
    "in this session",
    "session summary",
    "chat transcript",
    "maintainer decision",
    "maintainer asked",
    "as agreed with",
    "docs/internal/",
)
VALUE_FLAGS = ("-m", "--message", "-b", "--body")
FILE_FLAGS = ("-F", "--file", "--body-file")


def read_file(name: str, cmd: Cmd) -> str:
    """A message file's text; `-` is stdin, which is the heredoc fed to this command; unreadable is empty."""
    if name == "-":
        return cmd.doc
    try:
        return Path(name).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def message_text(cmd: Cmd, args: list[str]) -> str:
    """Every message or body the arguments carry, the way git and gh consume -m/-b/-F."""
    found: list[str] = []
    items = iter(args)
    for arg in items:
        cluster = re.fullmatch(r"-[^-]*?[mb](.*)", arg, re.DOTALL)
        if arg in VALUE_FLAGS:
            found.append(next(items, ""))
        elif arg in FILE_FLAGS:
            found.append(read_file(next(items, ""), cmd))
        elif arg.startswith(("--message=", "--body=")):
            found.append(arg.split("=", 1)[1])
        elif arg.startswith(("--file=", "--body-file=")):
            found.append(read_file(arg.split("=", 1)[1], cmd))
        elif arg.startswith("-F") and not arg.startswith("--"):
            found.append(read_file(arg[2:], cmd))
        elif cluster and not arg.startswith("--"):
            found.append(cluster.group(1) or next(items, ""))
    return " ".join(found)


def publishes(cmd: Cmd) -> list[str] | None:
    """The arguments after `git commit` or `gh pr create|edit`, or None for any other command."""
    if cmd.name == "git":
        sub, _, rest = git_parts(cmd.args)
        return rest if sub == "commit" else None
    words = [arg for arg in cmd.args if not arg.startswith("-")]
    if cmd.name == "gh" and "pr" in words and words[words.index("pr") + 1 :][:1] in (["create"], ["edit"]):
        return cmd.args
    return None


def check(raw: str) -> str | None:
    """The marker a commit message or PR body carries, or None."""
    for cmd in commands(raw):
        args = publishes(cmd)
        if args is None:
            continue
        text = message_text(cmd, args).lower()
        for marker in MARKERS:
            if marker in text:
                return (
                    f"commit message or PR body narrates the development process ('{marker}'). Describe the change "
                    "itself; keep conversations, plans, session links and decision trails out of published history -- "
                    "on a public repo every message is published forever. If this phrase is legitimate here, edit "
                    "the MARKERS list in this guard."
                )
    return None


def run(argv: list[str]) -> int:
    """Exit 1 blocks, 2 reports a guard fault (never a verdict), 0 allows."""
    try:
        reason = check(os.environ.get("CHOCK_RAW_COMMAND") or shlex.join(argv))
    except Exception as exc:  # noqa: BLE001 -- a guard fault must not look like a block
        print(f"protect-commit-privacy: internal error ({type(exc).__name__}); command not checked", file=sys.stderr)
        return 2
    if reason:
        print(f"BLOCKED: {reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))

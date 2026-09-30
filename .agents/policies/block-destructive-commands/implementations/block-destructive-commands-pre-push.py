#!/usr/bin/env python3
# Refuse a push that rewrites remote history: any ref whose remote value is not an ancestor of what is pushed.
# git feeds pre-push one line per ref, "<local ref> <local sha> <remote ref> <remote sha>", on stdin.
# --force-with-lease looks the same as --force here, so both are refused; a human who means it runs
# `git push --no-verify` (which block-no-verify refuses for an agent).

import subprocess
import sys

FIELDS = 4  # git's fixed pre-push line: local ref, local sha, remote ref, remote sha


def is_zero(sha: str) -> bool:
    """The all-zero object name git uses for "no such ref", in SHA-1 and SHA-256 repositories alike."""
    return not sha.strip("0")


def is_ancestor(old: str, new: str) -> bool:
    """Whether `old` is an ancestor of `new`; an object this clone has never seen counts as not one."""
    done = subprocess.run(["git", "merge-base", "--is-ancestor", old, new], capture_output=True, check=False)  # noqa: S603, S607
    return done.returncode == 0


def rewritten(lines: list[str]) -> list[str]:
    """The remote refs a push would move sideways or backwards; new refs and deletions are not rewrites."""
    refs = []
    for line in lines:
        parts = line.split()
        if len(parts) != FIELDS:
            continue
        _local_ref, local, remote_ref, remote = parts
        if is_zero(local) or is_zero(remote) or remote == local:
            continue
        if not is_ancestor(remote, local):
            refs.append(remote_ref)
    return refs


def run(stdin: str) -> int:
    """Exit 1 refuses the push, 2 reports a fault in this check (the push is refused too), 0 lets it go."""
    try:
        refs = rewritten(stdin.splitlines())
    except Exception as exc:  # noqa: BLE001 -- say what failed instead of a bare traceback
        print(
            f"block-destructive-commands-pre-push: internal error ({type(exc).__name__}); push not checked",
            file=sys.stderr,
        )
        return 2
    if not refs:
        return 0
    print(
        f"BLOCKED: push would rewrite history on {', '.join(refs)} (non-fast-forward). "
        "Pull or rebase and push again; a force push needs a human running `git push --no-verify`.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(run("" if sys.stdin.isatty() else sys.stdin.read()))

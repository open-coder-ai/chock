#!/bin/sh
# fmt: off
"exec" "$(command -v python3 || command -v python)" "$0" "$@"
# fmt: on
# Refuse destructive commands (rm -rf on a root/home path, force pushes, drops, prunes); ask before branch -D.
# Best effort, not a security boundary: aliases, interpreters and indirect scripts are out of reach.

import os
import shlex
import sys
from collections.abc import Callable
from itertools import takewhile

from chock_shellparse import (
    POWERSHELL_REMOVERS,
    Cmd,
    abbreviates,
    after,
    commands,
    flags_of,
    git_parts,
    is_dangerous_target,
    operands,
    positionals,
    removes_root_recursively,
)

BLOCK, ASK = 1, 3
KUBECTL_VALUES = frozenset(("-n", "--namespace", "--context", "--cluster", "--user", "--kubeconfig", "--server", "-s"))
HELM_VALUES = frozenset(("-n", "--namespace", "--kube-context", "--kubeconfig", "--kube-apiserver", "--kube-token"))
DOCKER_VALUES = frozenset(("-H", "--host", "--context", "-c", "--config", "-l", "--log-level"))
AWS_VALUES = frozenset(("--profile", "--region", "--endpoint-url", "--output", "--query", "--ca-bundle", "--color"))
Verdict = tuple[int, str] | None


def refuse(text: str) -> Verdict:
    return BLOCK, f"BLOCKED: {text}"


def confirm(text: str) -> Verdict:
    return ASK, f"CONFIRM: {text}"


def block(reason: str) -> Verdict:
    return refuse(f"{reason} is not allowed without approval.")


def rm(cmd: Cmd) -> Verdict:
    flags = flags_of(cmd.args)
    if not (flags & {"-r", "-R", "--recursive"} and flags & {"-f", "--force"}):
        return None
    hit = next((t for t in operands(cmd.args) if is_dangerous_target(t)), None)
    return None if hit is None else block(f"destructive rm command targeting '{hit}'")


def git_push(flags: set[str], targets: list[str]) -> Verdict:
    forced = min((t for t in targets if t.startswith("+") or ":+" in t), default="")
    if flags & {"-f", "--force"}:
        return refuse("git push --force is not allowed; use --force-with-lease on a feature branch.")
    if forced:
        return refuse(
            f"git push with a '+' force-refspec ('{forced}') overwrites the remote ref; use --force-with-lease on a feature branch."
        )
    return None


def git_branch(flags: set[str], _targets: list[str]) -> Verdict:
    if "-D" in flags or (flags & {"-d", "--delete"} and flags & {"-f", "--force"}):
        return confirm("git branch -D deletes a branch even if unmerged; confirm, or use -d for a merged branch.")
    return None


def git(cmd: Cmd) -> Verdict:
    sub, _, rest = git_parts(cmd.args)
    flags, targets = flags_of(rest), operands(rest)
    if sub == "push":
        return git_push(flags, targets)
    if sub == "branch":
        return git_branch(flags, targets)
    refused = {
        "reset": any(abbreviates(f, "--hard", 3) for f in flags),
        "clean": any(f == "-f" or abbreviates(f, "--force", 3) for f in flags),
        "checkout": "." in targets,
    }
    return block(f"git {sub} " + {"reset": "--hard", "clean": "-f", "checkout": "."}[sub]) if refused.get(sub) else None


def kubectl(cmd: Cmd) -> Verdict:
    return block("kubectl delete") if positionals(cmd.args, KUBECTL_VALUES)[:1] == ["delete"] else None


def terraform(cmd: Cmd) -> Verdict:
    return block("terraform destroy") if operands(cmd.args)[:1] == ["destroy"] else None


def aws(cmd: Cmd) -> Verdict:
    items, flags = positionals(cmd.args, AWS_VALUES), flags_of(cmd.args)
    action = after(items, "s3")
    if action == "rm" and "--recursive" in flags:
        return block("aws s3 rm --recursive")
    return block("aws s3 rb --force") if action == "rb" and "--force" in flags else None


def dropdb(_cmd: Cmd) -> Verdict:
    return block("dropdb")


def helm(cmd: Cmd) -> Verdict:
    first = positionals(cmd.args, HELM_VALUES)[:1]
    return block("helm uninstall/delete") if first and first[0] in ("uninstall", "delete", "del", "un") else None


def docker(cmd: Cmd) -> Verdict:
    items = positionals(cmd.args, DOCKER_VALUES)
    if after(items, "volume") in ("rm", "remove", "prune"):
        return block("docker volume rm/prune")
    return block("docker system prune") if after(items, "system") == "prune" else None


def gcloud(cmd: Cmd) -> Verdict:
    return block("gcloud delete") if "delete" in operands(cmd.args) else None


def find(cmd: Cmd) -> Verdict:
    args = cmd.args
    if not ("-delete" in args or (({"-exec", "-execdir", "-ok"} & set(args)) and "rm" in args)):
        return None
    roots = list(takewhile(lambda arg: not arg.startswith(("-", "(", "!")), args))
    hit = next((r for r in roots or ["."] if is_dangerous_target(r)), None)
    return None if hit is None else block(f"find with -delete/-exec rm rooted at '{hit}'")


def shred(cmd: Cmd) -> Verdict:
    hit = next((t for t in operands(cmd.args) if is_dangerous_target(t)), None)
    return None if hit is None else block(f"{cmd.name} targeting '{hit}' (it discards the data, not just the link)")


def wipefs(cmd: Cmd) -> Verdict:
    flags = flags_of(cmd.args)
    return block("wipefs -a/-o (erases filesystem signatures)") if flags & {"-a", "--all", "-o", "--offset"} else None


def powershell_remove(cmd: Cmd) -> Verdict:
    if removes_root_recursively(cmd):
        return block("destructive PowerShell/cmd removal targeting a drive root or home path")
    return None


CHECKS: dict[str, Callable[[Cmd], Verdict]] = {
    "rm": rm,
    "git": git,
    "kubectl": kubectl,
    "terraform": terraform,
    "aws": aws,
    "dropdb": dropdb,
    "helm": helm,
    "docker": docker,
    "gcloud": gcloud,
    "find": find,
    "shred": shred,
    "truncate": shred,
    "wipefs": wipefs,
    **dict.fromkeys(POWERSHELL_REMOVERS, powershell_remove),
}


def check(raw: str) -> Verdict:
    """The verdict for a command line: a block wins over an ask, which wins over silence."""
    asked: Verdict = None
    for cmd in commands(raw):
        verdict = CHECKS[cmd.name](cmd) if cmd.name in CHECKS else None
        if verdict and verdict[0] == BLOCK:
            return verdict
        asked = asked or verdict
    return asked


def run(argv: list[str]) -> int:
    """Exit 1 blocks, 3 asks, 2 reports a guard fault (never a verdict), 0 allows."""
    try:
        verdict = check(os.environ.get("CHOCK_RAW_COMMAND") or shlex.join(argv))
    except Exception as exc:  # noqa: BLE001 -- a guard fault must not look like a block
        print(
            f"block-destructive-commands: internal error ({type(exc).__name__}); command not checked", file=sys.stderr
        )
        return 2
    if verdict:
        print(verdict[1], file=sys.stderr)
    return verdict[0] if verdict else 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))

#!/bin/sh
# fmt: off
"exec" "$(command -v python3 || command -v python)" "$0" "$@"
# fmt: on
# Refuse git --no-verify, the other ways of switching git hooks off, and an agent setting a person-only override.

import os
import re
import shlex
import sys
from itertools import pairwise

from chock_shellparse import Cmd, commands, git_parts

HOOKS_KEY = "core.hookspath"
# git commit options whose value is the NEXT argument: a message that starts with -n is not a flag.
TAKES_VALUE = frozenset(
    ("-m", "-F", "-C", "-c", "-t", "--message", "--file", "--author", "--date", "--template", "--fixup", "--squash")
)
# --no-verify is a long option of these; a short -n means it only on commit and am (merge and rebase read -n as --no-stat).
HOOK_SUBS = frozenset(("commit", "push", "merge", "am", "rebase"))
SHORT_N_SUBS = frozenset(("commit", "am"))
PREFIX_FLOOR = 9
# Person-only variables: the engine reads CHOCK_ALLOW (answers an ask gate), CHOCK_AGENT_COMMIT (0/false says a person is
# committing) and the agent markers CLAUDECODE / AI_AGENT; limit-diff-size reads CHOCK_ALLOW_LARGE_DIFF, CHOCK_DIFF_LIMIT.
OVERRIDE = re.compile(r"CHOCK_(?:AGENT_COMMIT|DIFF_LIMIT|ALLOW\w*)|CLAUDECODE|AI_AGENT", re.IGNORECASE)
REMOVAL = frozenset(("CLAUDECODE", "AI_AGENT", "CHOCK_AGENT_COMMIT"))  # hiding these makes an agent's commit a person's
MARKERS = "(CLAUDECODE|AI_AGENT|CHOCK_AGENT_COMMIT)(?!\\w)"
WIPED = "CHOCK_ENV_WIPED"
ASSIGN = re.compile(r"([A-Za-z_]\w*)\+?=")
# Spellings the lexer drops are rewritten to the plain NAME=v it knows; text inside quotes stays data either way.
REWRITES = tuple(
    (re.compile(pattern, re.IGNORECASE), repl)
    for pattern, repl in (
        (
            r"(?:\$\{?env:((?:CHOCK_|CLAUDECODE|AI_AGENT)\w*)\}?\s*[+.]?|\b(CHOCK_\w+|CLAUDECODE|AI_AGENT)\+)=",
            r"\1\2=",
        ),  # $env:X = v, X+=v
        (rf"(?<![\w-])(?:-u\s*|--unset(?:\s+|=)){MARKERS}", r"\1="),  # env -u X, env --unset=X
        (rf"(?<![\w-])export\s+-[a-z]*n[a-z]*(?:\s+[a-z_]\w*)*?\s+{MARKERS}", r"\1="),  # export -n X
        (
            r"(?<![\w./-])env((?:\s+-\S*(?:\s+[^-\s]\S*)?)*?)\s+(?:-[a-z]*i[a-z]*|--ignore-environment|-)(?=\s|$)",
            rf"env\1 {WIPED}=1",  # env -i wipes the markers
        ),
    )
)
PS_PATH = re.compile(r"env:/?(\w+)$", re.IGNORECASE)
DECLARERS = frozenset(("declare", "typeset", "readonly", "local", "make", "gmake"))
PS_SETTERS = frozenset(("set-item", "si", "new-item", "ni", "set-content", "sc", "add-content", "ac"))
PS_REMOVERS = frozenset(("remove-item", "ri", "clear-item", "ci", "rm", "del", "erase"))
# A short cluster starting with one of these carries that option's value: `-mnote` is a message.
VALUE_CLUSTER = ("-m", "-F", "-u", "-C", "-c", "-S")


def hooks_path_keys(conf: list[str], env: dict[str, str]) -> list[str]:
    """Config keys set for one git command by -c/--config-env, GIT_CONFIG_COUNT/KEY_n or GIT_CONFIG_PARAMETERS."""
    keys = [item.split("=", 1)[0] for item in conf if "=" in item]
    count = env.get("GIT_CONFIG_COUNT", "")
    keys += [env.get(f"GIT_CONFIG_KEY_{i}", "") for i in range(min(int(count), 64) if count.isdigit() else 0)]
    keys += re.findall(r"'([^'=]+)'?=", env.get("GIT_CONFIG_PARAMETERS", ""))
    return [key.lower() for key in keys]


def config_sets_hooks(rest: list[str]) -> bool:
    """`git config core.hooksPath <value>` in any scope; reading or unsetting it is not a bypass."""
    operands = [arg for arg in rest if not arg.startswith("-")]
    reading = {"--get", "--get-all", "--get-regexp", "-l", "--list", "--unset", "--unset-all"} & set(rest)
    at = [i for i, arg in enumerate(operands) if arg.lower() == HOOKS_KEY]
    return bool(at) and not reading and at[0] + 1 < len(operands)


def is_no_verify(arg: str) -> bool:
    """--no-verify or any unambiguous prefix of it; git's floor is --no-veri (shorter collides with --no-verbose)."""
    return len(arg) >= PREFIX_FLOOR and "--no-verify".startswith(arg)


def is_short_n(arg: str) -> bool:
    """A short cluster containing -n, unless it starts with an option whose attached text is a value."""
    return re.fullmatch(r"-[^-].*", arg) is not None and "n" in arg and not arg.startswith(VALUE_CLUSTER)


def skips_verify(sub: str, rest: list[str]) -> bool:
    """--no-verify on a hook-running subcommand; a short -n only where it means that (not push --dry-run, not merge --no-stat)."""
    skip = False
    for arg in rest:
        if arg == "--":
            break
        if skip:
            skip = False
        elif is_no_verify(arg) or (sub in SHORT_N_SUBS and is_short_n(arg)):
            return True
        else:
            skip = arg in TAKES_VALUE
    return False


def is_override(name: str) -> bool:
    return OVERRIDE.fullmatch(name) is not None


def assigned(words: list[str]) -> list[str]:
    """Override names written as NAME=value among `words`."""
    return [m.group(1) for w in words if (m := ASSIGN.match(w)) and is_override(m.group(1))]


def set_by(cmd: Cmd, after: Cmd | None) -> list[str]:
    """Names one command sets, blanks or removes: env prefix, env/export (carried in cmd.env), declare, make, set, unset, PowerShell."""
    found = [name for name in cmd.env if is_override(name)]
    args, name = cmd.args, cmd.name
    if name == "git" and WIPED in cmd.env and git_parts(args)[0] in HOOK_SUBS:
        found.append("CLAUDECODE/AI_AGENT (env -i wipes them)")
    if name in DECLARERS:
        found += assigned(args)
    elif name == "unset":
        found += [a for a in args if a.upper() in REMOVAL]
    elif name == "set":
        erasing = any(re.fullmatch(r"-[a-z]*e[a-z]*|--erase", a, re.IGNORECASE) for a in args)
        found += [a for a in args if erasing and a.upper() in REMOVAL] + assigned(args)
        found += [a for a, nxt in pairwise(args) if is_override(a) and not nxt.startswith("-")]
    elif name in ("setx", "setenv"):
        found += [a.split("=", 1)[0] for a in args if is_override(a.split("=", 1)[0])]
    elif name in PS_SETTERS:
        found += [m.group(1) for a in args if (m := PS_PATH.search(a)) and is_override(m.group(1))]
    elif name in PS_REMOVERS:
        found += [m.group(1) for a in args if (m := PS_PATH.search(a)) and m.group(1).upper() in REMOVAL]
    elif name.endswith("setenvironmentvariable") and after is not None:
        found += [w for w in re.split(r"[,\s]+", " ".join([after.name, *after.args])) if is_override(w)]
    return found


def overrides_set(raw: str) -> list[str]:
    """Names the command line sets, blanks or removes. A trailing `true` carries a bare `export X=1` out to a command that shows it."""
    text = raw
    for pattern, repl in REWRITES:
        text = pattern.sub(repl, text)
    cmds = commands(f"{text}\ntrue")
    return [name.upper() for cmd, after in zip(cmds, [*cmds[1:], None], strict=True) for name in set_by(cmd, after)]


def check(raw: str) -> str | None:
    """The reason a command switches hooks off or sets a person-only override, or None."""
    if named := overrides_set(raw):
        return (
            f"changing {named[0]} is refused: it decides whether a gate sees an agent's commit, or answers one, "
            "and only a person may. Do not set, blank or remove it in any form; ask the person to run the command "
            "themselves with it changed."
        )
    for cmd in commands(raw):
        if cmd.name != "git":
            continue
        sub, conf, rest = git_parts(cmd.args)
        if sub == "config" and config_sets_hooks(rest):
            return "git config core.hooksPath disables every hook, exactly as --no-verify does. Fix the failing hook instead."
        if sub not in HOOK_SUBS:
            continue
        if HOOKS_KEY in hooks_path_keys(conf, cmd.env):
            return f"git {sub} with core.hooksPath set disables every hook, exactly as --no-verify does. Fix the failing hook instead of routing around it."
        if skips_verify(sub, rest):
            return f"git {sub} --no-verify is not allowed. Fix the hook failure instead."
    return None


def run(argv: list[str]) -> int:
    """Exit 1 blocks, 2 reports a guard fault (never a verdict), 0 allows."""
    try:
        reason = check(os.environ.get("CHOCK_RAW_COMMAND") or shlex.join(argv))
    except Exception as exc:  # noqa: BLE001 -- a guard fault must not look like a block
        print(f"block-no-verify: internal error ({type(exc).__name__}); command not checked", file=sys.stderr)
        return 2
    if reason:
        print(f"BLOCKED: {reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))

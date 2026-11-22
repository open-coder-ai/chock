"""The two things chock says about an adopter's .gitignore: what must stay out, and what must stay in.

The gate outcome log is per machine and grows on every commit, so it is ignored. The gate runtime
(`.chock/bin/`) and the compiled gates (`.chock/compiled/`) are what every agent hook and git hook
runs, so they are tracked -- explicitly, because a *global* ignore rule reaches them otherwise: the
`bin/` in the Visual Studio, .NET and Java gitignore templates matches `.chock/bin/`, `git add -A`
skips it, and every clone, CI checkout and `git clean -x` then has hooks naming a file that is not
there. A repository's own .gitignore outranks the global excludes file, so the negation wins.

Written once, appended, never rewritten: a rule the adopter already has, in a form git honours the
same way, is left alone.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path

from chock.emit import write_generated
from chock.output import warn_once

GATE_LOG_IGNORE = ".chock/log/"
#: The per-session tool-call log: per machine, a record per tool call, pruned after a week.
SESSION_STATE_IGNORE = ".chock/state/"
#: A person's `chock stop`: local state for one machine's agents, never committed (CI would read nothing from it).
STOP_FILE_IGNORE = ".chock/stop.json"
#: Re-included whatever a global excludes file says: the directories (against a `bin/` rule) and
#: everything under them (against a rule that names the files, a `*.json`, say).
TRACKED_RUNTIME = ("!.chock/bin/", "!.chock/bin/**", "!.chock/compiled/", "!.chock/compiled/**")

#: The installed policy trees, re-included the same way: a policy's Python package can hold a `build/`
#: sub-package that a `build/` rule elsewhere would drop. Bytecode stays out, so those two ignores come
#: after the negations -- within one .gitignore the last matching rule wins.
TRACKED_POLICIES = ("!.agents/policies/", "!.agents/policies/**")
POLICY_BYTECODE_IGNORE = (".agents/policies/**/__pycache__/", ".agents/policies/**/*.pyc")
#: The runtime's own bytecode: `.chock/bin/` holds Python the hooks import (the gate runner, the
#: session log), so running one writes `__pycache__` there, which `!.chock/bin/**` would re-include.
RUNTIME_BYTECODE_IGNORE = (
    ".chock/bin/**/__pycache__/",
    ".chock/bin/**/*.pyc",
    ".chock/compiled/**/__pycache__/",
    ".chock/compiled/**/*.pyc",
)

#: Claude Code saves each approved command here, secrets included; the vendor documents the file as local.
CLAUDE_LOCAL_SETTINGS = ".claude/settings.local.json"
_CLAUDE_LOCAL_COMMENT = (
    "# chock: Claude Code saves approved commands here, secrets included; the vendor documents it as local"
)

_BLOCKS = (
    ((GATE_LOG_IGNORE,), "# chock: the gate outcome log is per machine and grows on every commit"),
    ((SESSION_STATE_IGNORE,), "# chock: the per-session tool-call log is per machine and never shared"),
    ((STOP_FILE_IGNORE,), "# chock: a stop (`chock stop`) is local to this machine and never committed"),
    (
        TRACKED_RUNTIME,
        "# chock: the gate runtime and compiled gates are what every hook runs -- tracked even where\n"
        "# a global rule (a `bin/` from a Visual Studio or Java template) would ignore them",
    ),
    (
        TRACKED_POLICIES,
        "# chock: installed policies are tracked whole -- a policy's `build/` sub-package must reach every\n"
        "# clone, whatever a `build/`, `out/` or `target/` rule elsewhere says",
    ),
    (
        (*POLICY_BYTECODE_IGNORE,),
        "# chock: bytecode under the policies is per machine (must stay after the rules above)",
    ),
    (
        RUNTIME_BYTECODE_IGNORE,
        "# chock: bytecode under the runtime and compiled gates is per machine (must stay after the rules above)",
    ),
)


def _normal(rule: str) -> str:
    return rule.strip().rstrip("/")


def _eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _append(path: Path, rule: str, comment: str) -> None:
    """Append `rule` under `comment` unless an equivalent line is there; keep the file's line endings."""
    existing = path.read_bytes().decode("utf-8") if path.exists() else ""
    lines = {_normal(line) for line in existing.splitlines()}
    if _normal(rule) in lines:
        return
    if any(line.startswith("!") and line[1:].lstrip("/") == _normal(rule) for line in lines):
        warn_once(
            ("claude-local-settings-unignored", path.name),
            f"{path.name} un-ignores {rule} on purpose; chock leaves it alone",
        )
        return
    eol = _eol(existing)
    joiner = "" if not existing or existing.endswith("\n") else eol
    write_generated(path, existing + joiner + comment + eol + rule + eol)


def _is_tracked(repo_root: Path, rel: str) -> bool:
    git = shutil.which("git")
    if git is None:
        return False
    result = subprocess.run(  # noqa: S603 -- asking git whether it tracks one path
        [git, "-C", str(repo_root), "ls-files", "--error-unmatch", "--", rel],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _ensure_claude_local_settings(repo_root: Path) -> None:
    _append(repo_root / ".gitignore", CLAUDE_LOCAL_SETTINGS, _CLAUDE_LOCAL_COMMENT)
    dockerignore = repo_root / ".dockerignore"
    if dockerignore.exists():
        _append(dockerignore, CLAUDE_LOCAL_SETTINGS, _CLAUDE_LOCAL_COMMENT)
    if _is_tracked(repo_root, CLAUDE_LOCAL_SETTINGS):
        warn_once(
            ("claude-local-settings-tracked",),
            f"{CLAUDE_LOCAL_SETTINGS} is tracked, so the ignore rule does not hide it. Untrack it:\n"
            f"  git rm --cached {CLAUDE_LOCAL_SETTINGS}\n  git commit -m 'Stop tracking Claude Code local settings'",
        )


def ensure_git_rules(repo_root: Path, agents: Iterable[str] = ()) -> None:
    """Append whichever of chock's rules the repository's .gitignore does not already carry."""
    repo_root = Path(repo_root)
    gitignore = repo_root / ".gitignore"
    existing = gitignore.read_bytes().decode("utf-8") if gitignore.exists() else ""
    eol = _eol(existing)
    present = {_normal(line) for line in existing.splitlines()}
    added = ""
    for rules, comment in _BLOCKS:
        missing = [rule for rule in rules if _normal(rule) not in present]
        if missing:
            added += comment.replace("\n", eol) + eol + "".join(f"{rule}{eol}" for rule in missing)
    if added:
        joiner = "" if not existing or existing.endswith("\n") else eol
        write_generated(gitignore, existing + joiner + added)
    if "claude" in set(agents):
        _ensure_claude_local_settings(repo_root)

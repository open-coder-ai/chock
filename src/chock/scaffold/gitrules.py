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

from pathlib import Path

from chock.emit import write_generated

GATE_LOG_IGNORE = ".chock/log/"
#: Re-included whatever a global excludes file says: the directories (against a `bin/` rule) and
#: everything under them (against a rule that names the files, a `*.json`, say).
TRACKED_RUNTIME = ("!.chock/bin/", "!.chock/bin/**", "!.chock/compiled/", "!.chock/compiled/**")

#: The installed policy trees, re-included the same way: a policy's Python package can hold a `build/`
#: sub-package that a `build/` rule elsewhere would drop. Bytecode stays out, so those two ignores come
#: after the negations -- within one .gitignore the last matching rule wins.
TRACKED_POLICIES = ("!.agents/policies/", "!.agents/policies/**")
POLICY_BYTECODE_IGNORE = (".agents/policies/**/__pycache__/", ".agents/policies/**/*.pyc")

_BLOCKS = (
    ((GATE_LOG_IGNORE,), "# chock: the gate outcome log is per machine and grows on every commit"),
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
)


def _normal(rule: str) -> str:
    return rule.strip().rstrip("/")


def ensure_git_rules(repo_root: Path) -> None:
    """Append whichever of chock's rules the repository's .gitignore does not already carry."""
    gitignore = Path(repo_root) / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    present = {_normal(line) for line in existing.splitlines()}
    added = ""
    for rules, comment in _BLOCKS:
        missing = [rule for rule in rules if _normal(rule) not in present]
        if missing:
            added += comment + "\n" + "".join(f"{rule}\n" for rule in missing)
    if not added:
        return
    joiner = "" if not existing or existing.endswith("\n") else "\n"
    write_generated(gitignore, existing + joiner + added)

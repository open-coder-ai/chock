"""Hook targets: every file a chock-written agent hook runs must exist here and in every clone."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from chock import vendors
from chock.hooks.in_agent_install import WIRED_VENDORS, agent_hooks_rel
from chock.validation.report import Finding, Report

#: A file an agent hook command runs or hands the gate: the runtime (`.chock/bin/<vendor>.py`)
#: and the compiled gate it reads. chock is the only writer of both directories, so naming a
#: path under them identifies an entry as chock's own, independent of the vendor-specific shapes
#: `in_agent_merged.py`/`in_agent_generic.py` merge it through.
_BIN_TARGET_RE = re.compile(r"\.chock/(?:bin/[\w.-]+\.py|compiled/[\w./-]+\.json)")


def _ignore_rule(root: Path, rel: str) -> str | None:
    """The rule git would ignore `rel` by (`source:line:pattern`), or None; None outside a repo.

    A tracked file is never ignored, so this names only a file a clone would not have. Whether
    it is ignored is asked plainly: `check-ignore -v` also reports a path a `!` negation
    re-includes, and exits 0 for it, so it only names the rule once the answer is yes.
    """
    git = shutil.which("git")
    if git is None:
        return None
    base = [git, "-C", str(root), "check-ignore"]
    ignored = subprocess.run([*base, "-q", "--", rel], capture_output=True, check=False)  # noqa: S603 -- asking git
    if ignored.returncode != 0:
        return None
    named = subprocess.run([*base, "-v", "--", rel], capture_output=True, text=True, check=False)  # noqa: S603
    return named.stdout.strip().split("\t", 1)[0] or "a gitignore rule"


def _dangling_reason(root: Path, target: str) -> str | None:
    """Why a hook naming `target` fails -- here, or in every clone -- or None when it does not."""
    rule = _ignore_rule(root, target)
    if rule is not None:
        return (
            f"is ignored by git ({rule}), so a clone, a teammate's checkout or CI has no such file "
            "and the hook fails there. A global `bin/` rule is the usual cause: `chock sync` adds "
            "`!.chock/bin/` and `!.chock/compiled/` to .gitignore; commit them and the files."
        )
    if not (root / target).exists():
        return "does not exist. Run `chock sync` to reinstall or uninstall this vendor's hooks."
    return None


def check_dangling_hook_targets(root: Path, report: Report) -> None:
    """A chock-written hook entry naming a file that is missing, or that git would not keep.

    `sync` wires in-agent hooks only for the vendors `supported_agents` names and prunes a
    vendored runtime once its vendor falls out of that list (`recompile.py`); a hook config
    still naming the deleted runtime is a client-side failure on every tool call, silent to
    both `chock sync --check` and `chock check` unless something reads the config back. A
    runtime that exists here but is git-ignored fails the same way in every other checkout:
    there, no hook can start the gate at all.
    """
    paths = [root / vendors.config_path(vendor) for vendor in WIRED_VENDORS]
    paths.append(root / agent_hooks_rel())

    seen: set[tuple[str, str]] = set()
    for path in paths:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for target in _BIN_TARGET_RE.findall(text):
            key = (str(path), target)
            if key in seen:
                continue
            seen.add(key)
            reason = _dangling_reason(root, target)
            if reason is not None:
                report.add(Finding(str(path), "dangling_hook_target", "error", f"{path} runs {target}, which {reason}"))

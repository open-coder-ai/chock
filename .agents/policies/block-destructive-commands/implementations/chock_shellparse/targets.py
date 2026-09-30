"""Paths and PowerShell removals that are never a routine cleanup (stdlib only; shared byte for byte by the guards)."""

import re

from .args import abbreviates
from .parse import Cmd

# Root, home, the working directory and its parent: `rm -rf` on any of them (or below an absolute path) is refused.
_DANGEROUS = re.compile(r"(/|~(/|$)|\$\{?HOME\}?(/|$)|\.{1,2}$|\$env:(userprofile|home)(/|\\|$))", re.IGNORECASE)
_DRIVE = re.compile(r"[a-z]:([/\\]|$)", re.IGNORECASE)
POWERSHELL_REMOVERS = frozenset(("remove-item", "ri", "rd", "rmdir", "del", "erase"))


def is_dangerous_target(path: str) -> bool:
    return _DANGEROUS.match(path) is not None


def removes_root_recursively(cmd: Cmd) -> bool:
    """Remove-Item/rd/del -Recurse (or /s) aimed at a drive, root or home path; a relative target is routine."""
    args = [arg.lower() for arg in cmd.args]
    recursive = any(a == "/s" or abbreviates(a.split(":")[0], "-recurse", 2) for a in args)
    targets = [a for a in args if not re.fullmatch(r"-.*|/[a-z]", a)]
    return recursive and any(is_dangerous_target(t) or _DRIVE.match(t) for t in targets)

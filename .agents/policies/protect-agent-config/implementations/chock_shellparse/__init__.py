"""Shell command parsing shared by the catalog's Python guards; every policy ships an identical copy."""

from .args import abbreviates, after, flags_of, operands, positionals
from .parse import Cmd, commands, git_parts, is_powershell
from .targets import POWERSHELL_REMOVERS, is_dangerous_target, removes_root_recursively
from .writes import writes_files

__all__ = [
    "POWERSHELL_REMOVERS",
    "Cmd",
    "abbreviates",
    "after",
    "commands",
    "flags_of",
    "git_parts",
    "is_dangerous_target",
    "is_powershell",
    "operands",
    "positionals",
    "removes_root_recursively",
    "writes_files",
]

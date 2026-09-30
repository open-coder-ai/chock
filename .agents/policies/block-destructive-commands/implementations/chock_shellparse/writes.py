"""Whether a parsed command may write or delete a path (stdlib only; shared byte for byte by the guards)."""

import re
from collections.abc import Callable

from .parse import Cmd, git_parts

Hit = Callable[[str], bool]
_ALL_OPERANDS = (
    *("tee", "rm", "mv", "chmod", "chown", "truncate", "patch", "ed", "ex", "touch", "shred", "unlink", "rmdir"),
    *("set-content", "add-content", "out-file", "new-item", "clear-content", "remove-item", "move-item"),
    *("rename-item", "set-item", "tee-object", "sc", "ac", "ni", "ri", "mi", "rni", "del", "erase", "rd", "ren"),
)
_DEST_LAST = ("cp", "install", "ln", "rsync", "scp", "copy-item", "copy", "cpi")
_CODE_FLAGS = frozenset(("-c", "-e", "--eval", "-i", "--in-place", "-pi", "-ni", "-ne"))
_INTERPRETERS = ("python", "perl", "ruby", "node", "php")
_EXEC_FLAGS = frozenset(("-exec", "-execdir", "-ok"))


def _operands(cmd: Cmd) -> list[str]:
    return [arg for arg in cmd.args if not arg.startswith("-")]


def _destination(cmd: Cmd, hit: Hit) -> bool:
    """cp, install, ln: only the last operand (or --target-directory) is written."""
    operands = _operands(cmd)
    target = next((a.split("=", 1)[-1] for a in cmd.args if a.startswith("--target-directory")), "")
    return hit(target or (operands[-1] if operands else ""))


def _dd(cmd: Cmd, hit: Hit) -> bool:
    return any(arg.startswith("of=") and hit(arg[3:]) for arg in cmd.args)


def _every_operand(cmd: Cmd, hit: Hit) -> bool:
    """rm, mv, tee, Set-Content and the like: any path they are given is changed (-Path:x is unwrapped)."""
    return any(hit(arg) or hit(arg.split(":", 1)[-1]) for arg in cmd.args)


def _sed(cmd: Cmd, hit: Hit) -> bool:
    in_place = any(re.fullmatch(r"-[A-Za-z]*i.*|--in-place.*", arg) for arg in cmd.args)
    return in_place and any(hit(arg) for arg in _operands(cmd))


def _interpreter(cmd: Cmd, hit: Hit) -> bool:
    """python -c, perl -i, node -e: the code may write anything it names, so any argument naming the path counts."""
    code = bool(_CODE_FLAGS & set(cmd.args)) or any(re.fullmatch(r"-(?:pi|i)\..*", arg) for arg in cmd.args)
    return code and any(hit(arg) for arg in cmd.args)


def _find(cmd: Cmd, hit: Hit) -> bool:
    given = set(cmd.args)
    deleting = "-delete" in given or bool(given & _EXEC_FLAGS and given & set(_ALL_OPERANDS))
    return deleting and any(hit(arg) for arg in cmd.args)


def _git(cmd: Cmd, hit: Hit) -> bool:
    """checkout, restore, rm, mv overwrite or delete the worktree file."""
    sub, _, rest = git_parts(cmd.args)
    return sub in ("checkout", "restore", "rm", "mv") and any(hit(arg) for arg in rest)


_CHECKS: dict[str, Callable[[Cmd, Hit], bool]] = {
    **dict.fromkeys(_DEST_LAST, _destination),
    **dict.fromkeys(_ALL_OPERANDS, _every_operand),
    "dd": _dd,
    "sed": _sed,
    "find": _find,
    "git": _git,
}


def writes_files(cmd: Cmd, hit: Hit) -> bool:
    """Whether a command may write or delete a path `hit` accepts; reading it (cat, grep, cp FROM it) is not."""
    if any(hit(path) for path in cmd.writes):
        return True
    check = _CHECKS.get(cmd.name) or (_interpreter if cmd.name.startswith(_INTERPRETERS) else None)
    return check is not None and check(cmd, hit)

"""The portable hook command: git runs chock's committed launcher from the repository root."""

from __future__ import annotations

import contextlib
import re
import subprocess
import sys
from pathlib import Path, PurePath

from chock.emit import write_generated
from chock.resources import package_data_dir

#: Where the launcher lives in a consumer repo, beside the vendored runtimes it starts.
LAUNCHER_REL = ".chock/bin/launch.sh"

#: Local-only git config key naming the interpreter `chock sync` ran under on this machine.
PYTHON_CONFIG_KEY = "chock.python"

#: The oldest Python the vendored runtime runs on (chock's own `requires-python`).
MIN_PYTHON = (3, 11)

ALIAS = "chock-hook"

#: No launcher at git's top level (a nested repo, no repo, not synced) refuses with exit 2:
#: bash-as-sh exits 127 on a missing script, which agents treat as non-blocking.
_MISSING = f"test -f {LAUNCHER_REL} || {{ echo chock: no {LAUNCHER_REL} here, run chock sync --repo . >&2; exit 2; }}"

#: No `$`, no backslash, no single quote: bash, PowerShell and cmd.exe read it identically.
_PREFIX = f'git -c "alias.{ALIAS}=!{_MISSING}; sh {LAUNCHER_REL}" {ALIAS}'


def launcher_argv(*args: str) -> list[str]:
    """`hook_command` as an argv, for clients that take a command and an args list (MCP configs)."""
    return ["git", "-c", f"alias.{ALIAS}=!{_MISSING}; sh {LAUNCHER_REL}", ALIAS, *args]


#: A plugin has no repository root to resolve against, so its alias carries nothing but `sh`: git
#: supplies a POSIX sh under bash, PowerShell and cmd.exe alike, and the launcher's path is an
#: argument the client expands in its plugin-root token, as it did for `python3 "<path>"`.
PLUGIN_ALIAS = "chock-sh"

#: The launcher's name beside a plugin's packaged runtime.
PLUGIN_LAUNCHER = "launch.sh"

_TEMPLATE = package_data_dir("chock", "hooks", "data").joinpath("launch.sh").read_text(encoding="utf-8")


#: A bare word of a hook command; anything else a shell could read is refused, not escaped (no quoting style
#: reads the same to bash, PowerShell and cmd.exe).
PLAIN_WORD = re.compile(r"[A-Za-z0-9_@+=:,./-]+")

#: What a double-quoted path word may not hold: the characters the shell still reads inside double quotes.
QUOTED_UNSAFE = re.compile(r"""["$`\\\r\n]""")


def _readable_by_shell(word: str) -> bool:
    """Whether `word`, as `hook_command` writes it (a path double-quoted, anything else bare), holds a shell-read character."""
    return bool(QUOTED_UNSAFE.search(word)) if "/" in word else not PLAIN_WORD.fullmatch(word)


def hook_command(runtime: str, *args: str) -> str:
    """The command an agent config carries to run `runtime` (repo-relative) with `args`; a word a shell could read is refused."""
    if not PLAIN_WORD.fullmatch(runtime) or any(_readable_by_shell(arg) for arg in args):
        msg = f"hook command {[runtime, *args]!r} holds a character a shell would read; use plain repo-relative paths and flags"
        raise ValueError(msg)
    words = [f'"{arg}"' if "/" in arg else arg for arg in args]
    return " ".join([_PREFIX, runtime, *words])


#: A missing plugin launcher (root unset or wrong) refuses with exit 2 inside git's sh. The path is
#: never spliced in: git appends the launcher as "$1", read unquoted with no splitting or globbing.
#: Single-quoted, with no double quote or backslash, it reads the same to bash and PowerShell (Windows PowerShell drops
#: embedded double quotes); cmd.exe does not treat ' as a quote, and no plugin client runs it.
_PLUGIN_MISSING = (
    "set -f; IFS=; test -f $1 || "
    "{ echo chock: the plugin launcher is missing, so this call cannot be checked. Refusing. >&2; exit 2; }"
)


def plugin_interpreter(launcher: str) -> str:
    """What stands where a plugin hook said `python3`: git's sh running the shipped launcher at path `launcher`."""
    return f"git -c 'alias.{PLUGIN_ALIAS}=!{_PLUGIN_MISSING}; sh' {PLUGIN_ALIAS} \"{launcher}\""


#: The same refusal for a client whose Windows hook runner is cmd.exe passing `"` on as `\"` (store data
#: `windows_hook_command: quote_free`): no quote or space anywhere, words split by `${IFS}` in git's sh, and
#: every cmd.exe operator caret-escaped (cmd.exe strips the caret). `$1` is unquoted: the caller refuses a
#: launcher path holding whitespace, glob or cmd.exe metacharacters (hook_dir.resolve_root).
_QUOTE_FREE_MISSING = (
    "test -f $1||(echo chock: the plugin launcher is missing, so this call cannot be checked. Refusing.>&2;exit 2)&&sh"
)

#: cmd.exe operators the quote-free alias carries, each written `^<char>`.
CMD_OPERATORS = "|&<>()"


def cmd_escape(text: str) -> str:
    """`text` as one cmd.exe word: every space as `${IFS}` (git's sh splits there) and every operator caret-escaped."""
    text = text.replace(" ", "${IFS}")
    for char in CMD_OPERATORS:
        text = text.replace(char, f"^{char}")
    return text


def plugin_interpreter_quote_free(launcher: str) -> str:
    """`plugin_interpreter` with no quote and no space in any argument: `launcher` must hold neither."""
    return f"git -c alias.{PLUGIN_ALIAS}=!{cmd_escape(_QUOTE_FREE_MISSING)} {PLUGIN_ALIAS} {launcher}"


#: What a quote-free command's paths may not hold: whitespace, quotes, cmd.exe metacharacters, and what git's sh
#: would expand or split in an unquoted word (`$`, backquote, backslash, glob characters).
QUOTE_FREE_UNSAFE = re.compile(r"""[\s"'|&<>^%()$`\\*?\[!]""")

#: `_PREFIX` for the same cmd.exe runner: the repo launcher's refusal (exit 2) kept, written as `_QUOTE_FREE_MISSING`.
_QUOTE_FREE_PREFIX = (
    f"git -c alias.{ALIAS}=!"
    + cmd_escape(
        f"test -f {LAUNCHER_REL}||(echo chock: no {LAUNCHER_REL} here, run chock sync --repo .>&2;exit 2)"
        f"&&sh {LAUNCHER_REL}"
    )
    + f" {ALIAS}"
)


def hook_command_quote_free(command: str) -> str:
    """A `hook_command` with no quote or space in any argument; one whose words cannot be carried bare is refused."""
    words = command.removeprefix(f"{_PREFIX} ").split(" ")
    bare = [word[1:-1] if len(word) > 1 and word[0] == word[-1] == '"' else word for word in words]
    if not command.startswith(f"{_PREFIX} ") or any(not word or QUOTE_FREE_UNSAFE.search(word) for word in bare):
        msg = (
            f"{command!r}: this client runs hook commands through cmd.exe on Windows, where no quoting reaches git, "
            "so every argument must be a plain repo-relative path or flag"
        )
        raise ValueError(msg)
    return " ".join([_QUOTE_FREE_PREFIX, *bare])


def launcher_text() -> str:
    """The launcher script, with this chock's minimum Python filled in."""
    return _TEMPLATE.replace("__MIN_PYTHON_TEXT__", ".".join(map(str, MIN_PYTHON))).replace(
        "__MIN_PYTHON__", ", ".join(map(str, MIN_PYTHON))
    )


def write_launcher(repo_root: Path) -> Path:
    """Write the launcher into the consumer repo (LF, so git's sh reads it on Windows too)."""
    dest = Path(repo_root) / LAUNCHER_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_generated(dest, launcher_text())
    with contextlib.suppress(OSError):
        dest.chmod(0o755)
    return dest


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 -- fixed argv: git reading or setting this clone's own config
        ["git", *args],  # noqa: S607 -- git on PATH is the repo route's premise
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def record_interpreter(repo_root: Path) -> bool:
    """Name this interpreter in the clone's own .git/config; never committed. True when set."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        # Only when repo_root is the top level: inside another repo it is that repo's config.
        top = _git(repo_root, "rev-parse", "--show-toplevel").stdout.strip()
        if not top or Path(top).resolve() != Path(repo_root).resolve():
            return False
        return (
            _git(repo_root, "config", "--local", PYTHON_CONFIG_KEY, PurePath(sys.executable).as_posix()).returncode == 0
        )
    return False

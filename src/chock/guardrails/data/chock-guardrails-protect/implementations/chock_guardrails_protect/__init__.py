"""Which shell commands and writes would change a guardrails toggle file or accept custom code (stdlib only).

Paths are folded the way protect-agent-config folds them: backslashes read as slashes, `//` and `/./`
collapsed, `..` folded, letter case ignored, and links followed to the file they name. The shell side
is best effort: any word naming a file called guardrails.json, or the `.chock` folder in a command that
can move a folder into place, counts, and only commands that read are let through.
"""

from __future__ import annotations

import fnmatch
import itertools
import os
import posixpath
import re
import shlex
from collections.abc import Callable
from pathlib import Path

NAME = "guardrails.json"
#: The sha256 `chock bundle` records of the file it wrote, under `.chock/state/`: protected as the file is.
RECORD = "guardrails.sha256"
NAMES = (NAME, RECORD)
FOLDER = ".chock"
TOGGLE = f"{FOLDER}/{NAME}"
PROTECTED = (TOGGLE, f"{FOLDER}/state/{RECORD}")
#: The install marker inside every chock-built plugin: it records the custom-policy hashes a person accepted.
MARKER = "chock.selection.json"
#: `chock install --trust-local <id>=<sha256>` accepts custom code without asking: only a person passes it.
TRUST_FLAG = "--trust"

REFUSED = (
    "chock: an agent may not change .chock/guardrails.json or ~/.chock/guardrails.json (or their .chock/state "
    "record), the files that switch "
    "this bundle's guardrails on and off, nor run `chock bundle on|off` or `--adopt`. Reading is fine. Show the person "
    "the exact `chock bundle on|off <policy-id>` command to run in their own shell, and wait."
)

INSTALL_REFUSED = (
    "chock: an agent may not accept custom policy code for a person: no `chock install --trust-local` and no write "
    "to an install marker (chock.selection.json). Reading is fine. Show the person the exact "
    "`chock install --selection <file> --trust-local <id>=<sha256>` command to run in their own shell after they "
    "read the code, or let them run `chock install` in a terminal and answer its question; then wait."
)

#: Commands that only read the files they name (a write redirection is judged on its own).
READERS = frozenset(
    {
        "cat", "less", "more", "head", "tail", "grep", "egrep", "fgrep", "rg", "ag", "wc", "ls", "dir", "stat",
        "file", "diff", "cmp", "jq", "md5sum", "sha1sum", "sha256sum", "shasum", "b2sum", "echo", "printf",
        "test", "realpath", "readlink", "basename", "dirname", "od", "xxd", "hexdump", "strings", "bat",
        "get-content", "gc", "type", "select-string", "get-item", "get-childitem", "test-path",
    }
)  # fmt: skip
#: git subcommands that leave the working tree's files as they are.
GIT_READERS = frozenset({"status", "diff", "log", "show", "blame", "grep", "ls-files", "add", "commit", "rev-parse"})
#: Commands that run other text: with the toggle file named anywhere in the line, they could reach it unseen.
EXECUTORS = frozenset(
    {
        "sh", "bash", "zsh", "dash", "ksh", "fish", "eval", "source", ".", "xargs", "parallel", "env", "sudo",
        "doas", "nohup", "timeout", "nice", "exec", "command", "builtin", "python", "python3", "py", "node",
        "perl", "ruby", "php", "pwsh", "powershell", "cmd", "find", "awk", "sed", "invoke-expression", "iex",
    }
)  # fmt: skip
#: Commands that can put a folder in place of `.chock`, with a toggle file inside it.
FOLDER_WRITERS = frozenset({"mv", "cp", "ln", "rsync", "install", "tar", "unzip", "ditto", "move-item", "copy-item"})

_SEPARATORS = frozenset({";", "&", "&&", "|", "||", "|&", "(", ")", ";;"})
_GLOB = re.compile(r"[*?\[]")
_BRACES = re.compile(r"\{([^{}]*)\}")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
_EXE = ".exe"


def fold(path: str) -> str:
    """`path` lower-cased, backslashes read as slashes, `//`, `/./` and `..` folded."""
    text = path.replace("\\", "/").lower()
    if not text:
        return text
    return posixpath.normpath(re.sub(r"/{2,}", "/", text))


def _braces(text: str) -> list[str]:
    """Every spelling a brace list stands for (`{a,b}`), at most a few dozen."""
    found, todo = [], [text]
    while todo and len(found) < 64:  # noqa: PLR2004 -- a bound on expansion, not a rule
        item = todo.pop()
        match = _BRACES.search(item)
        if match is None:
            found.append(item)
            continue
        todo += [item[: match.start()] + part + item[match.end() :] for part in match.group(1).split(",")]
    return found


def _base_is(text: str, wanted: str) -> bool:
    """Whether the last segment of a folded path is `wanted`, or a glob or brace list that can name it."""
    for spelling in _braces(text):
        base = spelling.rstrip("/").rsplit("/", 1)[-1]
        if base == wanted or (_GLOB.search(base) and fnmatch.fnmatchcase(wanted, base)):
            return True
    return False


def _real(token: str, cwd: Path) -> str:
    """The folded path `token` names once `~` is expanded and links are followed, from `cwd`."""
    try:
        return fold(os.path.realpath(os.path.join(cwd, os.path.expanduser(token))))
    except (OSError, ValueError):
        return ""


def names_toggle(token: str, cwd: Path) -> bool:
    """Whether a shell word can name a toggle file or its record: as written, folded, or through a link."""
    folded, real = fold(token), _real(token, cwd)
    return any(name in folded or _base_is(folded, name) or _base_is(real, name) for name in NAMES)


def names_folder(token: str, cwd: Path) -> bool:
    """Whether a shell word names the `.chock` folder itself."""
    return _base_is(fold(token), FOLDER) or _base_is(_real(token, cwd), FOLDER)


def names_marker(token: str, cwd: Path) -> bool:
    """Whether a shell word can name an install marker: as written, folded, or through a link."""
    folded = fold(token)
    return MARKER in folded or _base_is(folded, MARKER) or _base_is(_real(token, cwd), MARKER)


def is_marker_path(path: str, root: Path) -> bool:
    """Whether a written path is an install marker, as written or through links."""
    return any(_base_is(folded, MARKER) for folded in (fold(path), _real(path, root)))


def is_toggle_path(path: str, root: Path) -> bool:
    """Whether a written path is a toggle file or its record (anywhere), as written or through links."""
    return any(
        folded == want or folded.endswith("/" + want)
        for folded in (fold(path), _real(path, root))
        for want in PROTECTED
    )


def _tokens(command: str) -> list[str]:
    """Shell words and operators; a newline separates commands. Unbalanced quotes fall back to a plain split."""
    text = command.replace("\r", "\n").replace("\n", " ; ")
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return text.split()


def _segments(tokens: list[str]) -> list[list[str]]:
    segments, current = [], []
    for token in tokens:
        if token in _SEPARATORS:
            segments.append(current)
            current = []
        else:
            current.append(token)
    return [s for s in [*segments, current] if s]


def _command(words: list[str]) -> tuple[str, list[str]]:
    """The segment's command name (lower-cased, `.exe` dropped) and its arguments, past leading assignments."""
    rest = list(words)
    while rest and _ASSIGNMENT.match(rest[0]):
        rest.pop(0)
    if not rest:
        return "", []
    name = rest[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name.removesuffix(_EXE), rest[1:]


def _is_redirect(token: str) -> bool:
    return ">" in token and set(token) <= set("<>&|0123456789")


def _bundle_switch(name: str, args: list[str]) -> bool:
    """`chock ... bundle on|off` or `bundle status --adopt`: the toggle file's writers, which only a person runs."""
    words = [name, *(a.lower() for a in args)]
    if "chock" not in words and not any(w.endswith("/chock") for w in words):
        return False
    if "bundle" in words and any(w.startswith("--adopt") for w in words):
        return True
    return any(w == "bundle" and nxt in ("on", "off") for w, nxt in itertools.pairwise(words))


def _split_redirects(words: list[str]) -> tuple[list[str], list[str]]:
    """(the words a command reads as arguments, the files its redirections write)."""
    plain: list[str] = []
    targets: list[str] = []
    skip = False
    for i, token in enumerate(words):
        if skip:
            skip = False
        elif _is_redirect(token):
            targets += words[i + 1 : i + 2]
            skip = True
        else:
            plain.append(token)
    return plain, targets


def _names_chock(words: list[str]) -> bool:
    """Whether a segment runs chock: `chock`, a path ending in it, or `python -m chock[.<module>]`."""
    lowered = [w.replace("\\", "/").lower().removesuffix(_EXE) for w in words]
    return any(w == "chock" or w.endswith("/chock") or w.startswith("chock.") for w in lowered)


def _trusts_local(words: list[str]) -> bool:
    """`chock ... --trust-local`, in any spelling argparse could read, with or without `=`."""
    return _names_chock(words) and any(w.split("=", 1)[0].lower().startswith(TRUST_FLAG) for w in words)


def _writes(words: list[str], cwd: Path, names: Callable[[str, Path], bool]) -> bool:
    """Whether a segment could write a file `names(token, cwd)` matches; readers and git readers pass."""
    name, args = _command(words)
    plain, targets = _split_redirects(words)
    if any(names(t, cwd) for t in targets) or any(
        _ASSIGNMENT.match(t) and names(t.split("=", 1)[1], cwd) for t in plain
    ):
        return True
    if not any(names(t, cwd) for t in plain) or name in READERS:
        return False
    sub = next((a.lower() for a in args if not a.startswith("-")), "")
    return not (name == "git" and sub in GIT_READERS)


def _segment_refused(words: list[str], cwd: Path) -> bool:
    name, args = _command(words)
    if _bundle_switch(name, args) or (name in FOLDER_WRITERS and any(names_folder(a, cwd) for a in args)):
        return True
    return _writes(words, cwd, names_toggle)


def _hidden(command: str, segments: list[list[str]], wanted: list[str]) -> bool:
    """Whether a line that names every `wanted` text also runs other text it could hide them in."""
    lowered = fold(command)
    if not all(w in lowered for w in wanted):
        return False
    return "$(" in command or "`" in command or any(_command(s)[0] in EXECUTORS for s in segments)


def install_refused(command: str, cwd: Path) -> bool:
    """Whether an agent's command could accept custom code: `--trust-local`, or a write to an install marker."""
    segments = _segments(_tokens(command))
    if any(_trusts_local(s) or _writes(s, cwd, names_marker) for s in segments):
        return True
    if TRUST_FLAG in fold(command) and any(_names_chock(s) for s in segments):
        return True  # the flag set in a variable or built elsewhere on the line that runs chock
    return _hidden(command, segments, ["chock", TRUST_FLAG]) or _hidden(command, segments, [MARKER])


def refuses(command: str, cwd: Path) -> bool:
    """Whether an agent's shell command could write a toggle file or switch a member."""
    segments = _segments(_tokens(command))
    if any(_segment_refused(words, cwd) for words in segments):
        return True
    named = any(name in fold(command) for name in NAMES) or any(names_toggle(t, cwd) for s in segments for t in s)
    if not named:
        return False
    return "$(" in command or "`" in command or any(_command(s)[0] in EXECUTORS for s in segments)


def refusal(command: str, cwd: Path) -> str | None:
    """The refusal an agent's shell command gets, or None when it may run."""
    if refuses(command, cwd):
        return REFUSED
    return INSTALL_REFUSED if install_refused(command, cwd) else None

"""Which shell commands and writes would change a guardrails toggle file (stdlib only).

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
from pathlib import Path

NAME = "guardrails.json"
FOLDER = ".chock"
TOGGLE = f"{FOLDER}/{NAME}"

REFUSED = (
    "chock: an agent may not change .chock/guardrails.json or ~/.chock/guardrails.json, the files that switch "
    "this bundle's guardrails on and off, nor run `chock bundle on|off`. Reading them is fine. Show the person "
    "the exact `chock bundle on|off <policy-id>` command to run in their own shell, and wait."
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
    """Whether a shell word can name a toggle file: as written, folded, or through a link."""
    folded = fold(token)
    return NAME in folded or _base_is(folded, NAME) or _base_is(_real(token, cwd), NAME)


def names_folder(token: str, cwd: Path) -> bool:
    """Whether a shell word names the `.chock` folder itself."""
    return _base_is(fold(token), FOLDER) or _base_is(_real(token, cwd), FOLDER)


def is_toggle_path(path: str, root: Path) -> bool:
    """Whether a written path is a toggle file (`.chock/guardrails.json` anywhere), as written or through links."""
    return any(folded == TOGGLE or folded.endswith("/" + TOGGLE) for folded in (fold(path), _real(path, root)))


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
    """`chock ... bundle on|off`: the toggle file's writer, which only a person runs."""
    words = [name, *(a.lower() for a in args)]
    if "chock" not in words and not any(w.endswith("/chock") for w in words):
        return False
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


def _segment_refused(words: list[str], cwd: Path) -> bool:
    name, args = _command(words)
    plain, targets = _split_redirects(words)
    if (
        _bundle_switch(name, args)
        or any(names_toggle(t, cwd) for t in targets)
        or any(_ASSIGNMENT.match(t) and names_toggle(t.split("=", 1)[1], cwd) for t in plain)
        or (name in FOLDER_WRITERS and any(names_folder(a, cwd) for a in args))
    ):
        return True
    if not any(names_toggle(t, cwd) for t in plain):
        return False
    if name in READERS:
        return False
    sub = next((a.lower() for a in args if not a.startswith("-")), "")
    return not (name == "git" and sub in GIT_READERS)


def refuses(command: str, cwd: Path) -> bool:
    """Whether an agent's shell command could write a toggle file or switch a member."""
    segments = _segments(_tokens(command))
    if any(_segment_refused(words, cwd) for words in segments):
        return True
    named = NAME in fold(command) or any(names_toggle(t, cwd) for s in segments for t in s)
    if not named:
        return False
    return "$(" in command or "`" in command or any(_command(s)[0] in EXECUTORS for s in segments)

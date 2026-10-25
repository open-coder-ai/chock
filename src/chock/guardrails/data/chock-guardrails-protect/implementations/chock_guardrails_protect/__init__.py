"""Which shell commands and writes would change a guardrails toggle file or accept custom code (stdlib only).

Paths are folded the way protect-agent-config folds them: backslashes read as slashes, `//` and `/./`
collapsed, `..` folded, letter case ignored, and links followed to the file they name. The shell side
is best effort: any word naming a file called guardrails.json, or the `.chock` folder in a command that
can move a folder into place, counts, and only commands that read are let through.
"""

from __future__ import annotations

import itertools
import re
import shlex
from collections.abc import Callable
from pathlib import Path

from .names import base_is, fold, real_path

NAME = "guardrails.json"
#: The sha256 `chock bundle` records of the file it wrote, under `.chock/state/`: protected as the file is.
RECORD = "guardrails.sha256"
NAMES = (NAME, RECORD)
FOLDER = ".chock"
TOGGLE = f"{FOLDER}/{NAME}"
PROTECTED = (TOGGLE, f"{FOLDER}/state/{RECORD}")
#: The decision log's settings, one per scope: how much chock logs is a person's call, raised or lowered.
LOG_SETTINGS = "chock-log.json"
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

LOG_REFUSED = (
    "chock: an agent may not change .chock/chock-log.json or ~/.chock/chock-log.json, the files that set how much "
    "chock logs (level, max_bytes), whether to raise or lower it. Reading is fine. Show the person the exact JSON "
    "to put in the file from their own editor or shell, and wait."
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
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
_EXE = ".exe"


def names_toggle(token: str, cwd: Path) -> bool:
    """Whether a shell word can name a toggle file or its record: as written, folded, or through a link."""
    folded, real = fold(token), real_path(token, cwd)
    return any(name in folded or base_is(folded, name) or base_is(real, name) for name in NAMES)


def names_folder(token: str, cwd: Path) -> bool:
    """Whether a shell word names the `.chock` folder itself."""
    return base_is(fold(token), FOLDER) or base_is(real_path(token, cwd), FOLDER)


def names_marker(token: str, cwd: Path) -> bool:
    """Whether a shell word can name an install marker: as written, folded, or through a link."""
    folded = fold(token)
    return MARKER in folded or base_is(folded, MARKER) or base_is(real_path(token, cwd), MARKER)


def names_log(token: str, cwd: Path) -> bool:
    """Whether a shell word can name a log settings file: as written, folded, or through a link."""
    folded = fold(token)
    return LOG_SETTINGS in folded or base_is(folded, LOG_SETTINGS) or base_is(real_path(token, cwd), LOG_SETTINGS)


def is_log_path(path: str, root: Path) -> bool:
    """Whether a written path is a log settings file (in any `.chock` folder), as written or through links."""
    return any(("/" + folded).endswith(f"/{FOLDER}/{LOG_SETTINGS}") for folded in (fold(path), real_path(path, root)))


def is_marker_path(path: str, root: Path) -> bool:
    """Whether a written path is an install marker, as written or through links."""
    return any(base_is(folded, MARKER) for folded in (fold(path), real_path(path, root)))


def is_toggle_path(path: str, root: Path) -> bool:
    """Whether a written path is a toggle file or its record (anywhere), as written or through links."""
    return any(
        folded == want or folded.endswith("/" + want)
        for folded in (fold(path), real_path(path, root))
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


#: Text that a name fragment held in a variable or an escape could complete into a protected path.
_EXPANDED = re.compile(r"\$|`")
#: Fragments a protected name can be assembled from; a write that expands a variable next to one is refused.
_FRAGMENTS = ("guard", "rails", "sha256")


def _expanded_write(words: list[str], command: str) -> bool:
    """Whether a segment writes through a path word built by expansion, on a line that mentions a protected fragment."""
    name, _ = _command(words)
    plain, targets = _split_redirects(words)
    written = targets + ([] if name in READERS else plain)
    if not any(_EXPANDED.search(word) for word in written):
        return False
    lowered = fold(command)
    return any(fragment in lowered for fragment in _FRAGMENTS)


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
    if any(_segment_refused(words, cwd) or _expanded_write(words, command) for words in segments):
        return True
    named = any(name in fold(command) for name in NAMES) or any(names_toggle(t, cwd) for s in segments for t in s)
    if not named:
        return False
    return "$(" in command or "`" in command or any(_command(s)[0] in EXECUTORS for s in segments)


def log_refused(command: str, cwd: Path) -> bool:
    """Whether an agent's shell command could write a log settings file."""
    segments = _segments(_tokens(command))
    return any(_writes(s, cwd, names_log) for s in segments) or _hidden(command, segments, [LOG_SETTINGS])


def refusal(command: str, cwd: Path) -> str | None:
    """The refusal an agent's shell command gets, or None when it may run."""
    if refuses(command, cwd):
        return REFUSED
    if log_refused(command, cwd):
        return LOG_REFUSED
    return INSTALL_REFUSED if install_refused(command, cwd) else None

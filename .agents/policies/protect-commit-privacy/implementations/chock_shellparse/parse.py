"""Split a shell command line into the simple commands it runs (stdlib only; shared byte for byte by the guards)."""

import os
import re
import shlex
from dataclasses import dataclass, field
from typing import NamedTuple


class Cmd(NamedTuple):
    """One simple command after wrappers are removed: program, arguments, environment, redirections, heredoc."""

    name: str
    args: list[str]
    env: dict[str, str]
    writes: list[str]
    reads: list[str]
    doc: str


@dataclass
class _Clause:
    words: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    reads: list[str] = field(default_factory=list)
    doc: str = ""


_QUOTED = r"""(?:[^\s;&|()<>'"\\`]|\\.|'[^']*'|"(?:[^"\\]|\\.)*")"""
_TOKEN = re.compile(
    r"(?P<ws>[ \t\r]+|\\\n)|(?P<nl>\n)|(?P<note>#[^\n]*)"
    r"|(?P<redir>[0-9]*(?:<<<|<<-?|>>|>&|>\||>|<&|<)|&>>?)"
    r"|(?P<end>&&|\|\||\|&|;;|[;&|()`]|(?<!\S)[{}](?!\S))"
    rf"|(?P<word>{_QUOTED}+)",
    re.DOTALL,
)
_PIECE = re.compile(r"'([^']*)'|\"((?:[^\"\\]|\\.)*)\"|\\(.)|([^'\"\\]+)", re.DOTALL)
_ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_WINPATH = re.compile(r"(?<=[\w.:~$-])\\(?=[\w.~$-])")
_POWERSHELL = re.compile(
    r"\b(?:get|set|add|out|new|remove|copy|move|rename|invoke|clear|write|select|start|import|export)-[a-z]{3,}"
    r"|\$env:|-(?:recurse|literalpath)\b",
    re.IGNORECASE,
)
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "ash"})
_PS_SHELLS = frozenset({"pwsh", "powershell"})
_DEPTH = 4
_WRAPPERS = {
    name: (frozenset(flags.split()), skip)
    for name, flags, skip in (
        ("sudo", "-u -g -h -p -C -D -R -T -U -r -t --user --group --host --prompt --chdir", 0),
        ("doas", "-u -C", 0),
        ("pkexec", "--user", 0),
        ("env", "-u -C -S --unset --chdir --split-string", 0),
        ("exec", "-a", 0),
        ("nice", "-n --adjustment", 0),
        ("ionice", "-c -n -p -t", 0),
        ("time", "-f -o --format --output", 0),
        ("timeout", "-s -k --signal --kill-after", 1),
        ("xargs", "-a -d -E -I -L -n -P -s --arg-file --delimiter --max-args --max-procs --replace", 0),
        ("stdbuf", "-i -o -e", 0),
    )
} | dict.fromkeys(
    (
        "command",
        "builtin",
        "nohup",
        "setsid",
        "rtk",
        "export",
        "do",
        "then",
        "else",
        "elif",
        "if",
        "while",
        "until",
        "!",
    ),
    (frozenset(), 0),
)
_GIT_VALUE = frozenset(
    {"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix", "--config-env"}
)


def _unquote(word: str) -> str:
    out = []
    for single, double, escaped, plain in _PIECE.findall(word):
        out.append(single or re.sub(r'\\(["\\$`])', r"\1", double) or escaped.strip("\n") or plain)
    return "".join(out)


class _Scan:
    """Split a command line into clauses at unquoted separators, collecting redirections and heredocs."""

    def __init__(self, text: str) -> None:
        self.text, self.pos, self.done, self.cur = text, 0, [], _Clause()
        self.redir, self.docs = "", []

    def run(self) -> list[_Clause] | None:
        while self.pos < len(self.text):
            match = _TOKEN.match(self.text, self.pos)
            if match is None:
                return None
            self.pos = match.end()
            kind = match.lastgroup
            if kind == "word":
                self._word(_unquote(match.group()))
            elif kind == "redir":
                self.redir = match.group().lstrip("0123456789")
            elif kind in ("end", "nl"):
                self._end()
                if kind == "nl":
                    self._bodies()
        self._end()
        return self.done

    def _word(self, text: str) -> None:
        op, self.redir = self.redir, ""
        if not op:
            self.cur.words.append(text)
        elif op in ("<<", "<<-"):
            self.docs.append((text, op == "<<-", self.cur))
        elif op == "<":
            self.cur.reads.append(text)
        elif op[0] in ">&" and not op.endswith("&"):
            self.cur.writes.append(text)

    def _end(self) -> None:
        if self.cur.words or self.cur.writes or self.cur.reads:
            self.done.append(self.cur)
        self.cur, self.redir = _Clause(), ""

    def _bodies(self) -> None:
        while self.docs:
            delim, strip, clause = self.docs.pop(0)
            lines = self.text[self.pos :].split("\n")
            body, used = [], len(lines)
            for index, line in enumerate(lines):
                if (line.strip("\t\r") if strip else line.rstrip("\r")) == delim:
                    used = index + 1
                    break
                body.append(line)
            clause.doc = "\n".join(body)
            self.pos += sum(len(line) + 1 for line in lines[:used])


def _words(part: str) -> list[str]:
    """Split one segment like a shell; a quote that is never closed makes the rest of the segment one word."""
    positions = [m.start() for m in re.finditer(r"['\"]", part)]
    for at in [len(part), *reversed(positions)]:
        try:
            return [*shlex.split(part[:at]), *([part[at + 1 :]] if at < len(part) else [])]
        except ValueError:
            continue
    return part.split()


def _crude(text: str) -> list[_Clause]:
    """Fallback when quoting does not balance: split on separators, then words; redirections are still seen."""
    found = []
    for part in re.split(r"&&|\|\||[;&|\n()`]", text):
        clause, words = _Clause(), iter(_words(part))
        for word in words:
            redirect = re.fullmatch(r"([^<>]*)(>>|>\||>|<)(.*)", word, re.DOTALL)
            if redirect is None:
                clause.words.append(word)
                continue
            head, op, tail = redirect.groups()
            if head and not head.isdigit():
                clause.words.append(head)
            target = tail or next(words, "")
            if target:
                (clause.reads if op == "<" else clause.writes).append(target)
        if clause.words or clause.writes or clause.reads:
            found.append(clause)
    return found


def _base(word: str) -> str:
    return re.sub(r"\.exe$", "", word.replace("\\", "/").rsplit("/", 1)[-1].lower())


def _strip(name: str, words: list[str]) -> list[str]:
    flags, skip = _WRAPPERS[name]
    i = 0
    while i < len(words) and words[i].startswith("-") and len(words[i]) > 1:
        if words[i] == "--":
            i += 1
            break
        i += 2 if words[i] in flags else 1
    return words[i + skip :]


def _inner(name: str, args: list[str]) -> str | None:
    """The script a shell-like command runs (bash -c, pwsh -Command, cmd /c, eval), or None."""
    if name == "eval":
        return " ".join(args)
    for i, arg in enumerate(args):
        low = arg.lower()
        shell = name in _SHELLS and arg[:1] == "-" and arg[1:2] != "-" and "c" in arg
        if shell or (name in _PS_SHELLS and low in ("-command", "-c")) or (name == "cmd" and low in ("/c", "/k")):
            return " ".join(args[i + 1 :])
    return None


def _resolve(clause: _Clause, env: dict[str, str], *, ps: bool, depth: int) -> tuple[list[Cmd], dict[str, str]]:
    words, local = list(clause.words), dict(env)
    while words:
        name = _base(words[0])
        if _ASSIGN.match(words[0]):
            key, _, value = words.pop(0).partition("=")
            local[key] = value
        elif name in _WRAPPERS:
            skip = name == "command" and words[1:2] in (["-v"], ["-V"])
            words = [] if skip else _strip(name, words[1:])
        else:
            break
    carry = [Cmd("", [], local, clause.writes, clause.reads, clause.doc)] if clause.writes or clause.reads else []
    if not words:
        return carry, local
    script = _inner(name, words[1:])
    if script is not None and depth < _DEPTH:
        found, after = _parse(script, local, ps=ps or name in _PS_SHELLS, depth=depth + 1)
        return found + carry, (after if name == "eval" else env)  # eval runs in this shell: its exports stay
    return [Cmd(name, words[1:], local, clause.writes, clause.reads, clause.doc)], env


def _parse(text: str, env: dict[str, str], *, ps: bool, depth: int) -> tuple[list[Cmd], dict[str, str]]:
    out = []
    for clause in _Scan(text).run() or _crude(text):
        cmds, env = _resolve(clause, env, ps=ps, depth=depth)
        out += cmds
    return out, env


def is_powershell(raw: str) -> bool:
    """CHOCK_TOOL says which shell ran the command when the engine sets it; otherwise read the text."""
    tool = os.environ.get("CHOCK_TOOL", "").lower()
    return tool in ("powershell", "pwsh") or (tool != "bash" and bool(_POWERSHELL.search(raw)))


def commands(raw: str) -> list[Cmd]:
    """Every simple command in a command line, unwrapped from bash -c, sudo, env, xargs, subshells and cd chains."""
    ps = is_powershell(raw)
    texts = [raw.replace("\\", "/").replace("`", "")] if ps else [raw, _WINPATH.sub("/", raw)]
    return [cmd for text in dict.fromkeys(texts) for cmd in _parse(text, {}, ps=ps, depth=0)[0]]


def git_parts(args: list[str]) -> tuple[str, list[str], list[str]]:
    """(subcommand, values of global -c/--config-env options, arguments after the subcommand) of a git command."""
    conf, i = [], 0
    while i < len(args):
        arg = args[i]
        if arg in _GIT_VALUE:
            if arg in ("-c", "--config-env") and i + 1 < len(args):
                conf.append(args[i + 1])
            i += 2
        elif arg.startswith("--config-env="):
            conf.append(arg[13:])
            i += 1
        elif arg.startswith("-"):
            i += 1
        else:
            return arg, conf, args[i + 1 :]
    return "", conf, []

"""The repo stop (`chock stop`): `.chock/stop.json` read fail-closed. Stdlib only; gate.py and every runtime carry it."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .constants import CASE_BLIND_PLATFORMS

# >>> gate.py 21
#: A person's stop for one repository: local state, never committed (`chock init` ignores it).
HALT_PARTS = (".chock", "stop.json")
HALT_ALL = "all"
#: The decision log's reason for every call a stop refused.
HALT_REASON = "stopped"
#: The policy id the log files a refusal under when no policy's hook made it, and the stop and resume lines.
HALT_POLICY = "chock-stop"
#: A client id as `--agent` takes it and a scope is written: anything else reads as every agent.
HALT_CLIENT_RE = re.compile(r"^[a-z0-9_]{1,32}$")
#: The runtime flag of the repo stop's own pre-tool hook, which `chock sync` wires for every client.
HALT_HOOK_FLAG = "--stop-check"
#: Every in-agent client id (`chock.vendors.in_agent_vendors()`, pinned by a test): a git marker naming
#: none of them cannot be told apart from a stopped client, so any stop reaches it.
HALT_CLIENTS = (
    "antigravity",
    "claude_code",
    "codex_cli",
    "cursor",
    "devin",
    "factory_droid",
    "gemini_cli",
    "goose",
    "grok",
    "mistral_vibe",
    "openhands",
    "tabnine",
    "vscode_copilot",
    "windsurf",
)
#: The machine-level registry under the person's home: one `<sha256 of the repository's realpath>.json` per stop,
#: so a runtime that cannot tell which repository its session is rooted in still sees every stop on the machine.
HALT_REGISTRY_PARTS = (".chock", "stops")
_HALT_REGISTRY_SUFFIX = ".json"
#: The machine-wide stop (`chock stop --everywhere`) in the registry: no sha256 hex digest starts with `_`.
HALT_EVERYWHERE_NAME = "_everywhere.json"
_HALT_EVERYWHERE_UNREADABLE = "~/.chock/stops/_everywhere.json exists but cannot be read, so every agent is refused"
_HALT_REGISTRY_UNREADABLE = "~/.chock/stops exists but cannot be read, so every agent is refused"
_HALT_GITDIR = "gitdir:"
_HALT_REASON_CAP = 200
_HALT_UNREADABLE = ".chock/stop.json exists but cannot be read, so every agent is refused"
_HALT_NO_REASON = "no reason given"


def _halt_read_file(path, unreadable):
    """The stop `path` holds as {scope, reason, ...}, or None when there is no file. A file that exists but
    cannot be read or parsed, or names no valid scope, stops every agent: fail closed."""
    stopped = {"scope": HALT_ALL, "reason": unreadable, "unreadable": True}
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError):
        return stopped if os.path.lexists(path) else None
    except (OSError, UnicodeError, ValueError):
        return stopped
    scope = doc.get("scope") if isinstance(doc, dict) else None
    if not isinstance(scope, str) or not (scope == HALT_ALL or HALT_CLIENT_RE.match(scope)):
        return stopped
    reason = doc.get("reason")
    return {**doc, "scope": scope, "reason": reason if isinstance(reason, str) else ""}


def halt_read(repo_root):
    """The stop in force for `repo_root`, or None; read fail-closed."""
    if repo_root is None:
        return None
    return _halt_read_file(Path(repo_root).joinpath(*HALT_PARTS), _HALT_UNREADABLE)


def halt_registry_dir():
    """`~/.chock/stops`: the machine-level registry of every stop in force."""
    return Path(os.path.expanduser("~")).joinpath(*HALT_REGISTRY_PARTS)


def halt_norm(path):
    """`path`'s realpath, casefolded where the filesystem ignores case (realpath keeps the case it was typed in)."""
    real = os.path.realpath(str(path))
    return real.casefold() if sys.platform in CASE_BLIND_PLATFORMS else real


def halt_registry_entry(repo_root):
    """The registry entry for `repo_root`, named by the sha256 of its normalised realpath."""
    key = hashlib.sha256(halt_norm(repo_root).encode("utf-8")).hexdigest()
    return halt_registry_dir() / f"{key}{_HALT_REGISTRY_SUFFIX}"


def halt_everywhere_entry():
    """`~/.chock/stops/_everywhere.json`: the machine-wide stop."""
    return halt_registry_dir() / HALT_EVERYWHERE_NAME


def halt_everywhere_read():
    """The machine-wide stop, reaching every agent whatever its scope says, or None. A file there that is not a
    regular one, or cannot be read or parsed, stops every agent: fail closed."""
    path = halt_everywhere_entry()
    if not os.path.lexists(path):
        return None
    unreadable = {"scope": HALT_ALL, "reason": _HALT_EVERYWHERE_UNREADABLE, "unreadable": True}
    regular = os.path.isfile(path) and not os.path.islink(path)
    stop = _halt_read_file(path, _HALT_EVERYWHERE_UNREADABLE) if regular else unreadable
    return {**(stop or unreadable), "scope": HALT_ALL, "everywhere": True}


def halt_registry_find(client, repos=None):
    """The machine-wide stop, else the first registry entry that reaches `client` (only those for `repos`, when
    given), or None. A registry that exists but cannot be listed, or an entry that cannot be read, refuses."""
    folder = halt_registry_dir()
    unreadable = {"scope": HALT_ALL, "reason": _HALT_REGISTRY_UNREADABLE, "unreadable": True}
    try:
        names = sorted(os.listdir(folder))
    except (FileNotFoundError, NotADirectoryError):
        return unreadable if os.path.lexists(folder) else None
    except OSError:
        return unreadable
    everywhere = halt_everywhere_read() if HALT_EVERYWHERE_NAME in names else None
    if everywhere is not None:
        return everywhere
    wanted = None if repos is None else {halt_registry_entry(repo).name for repo in repos}
    for name in names:
        if not name.endswith(_HALT_REGISTRY_SUFFIX) or (wanted is not None and name not in wanted):
            continue
        stop = _halt_read_file(folder / name, _HALT_REGISTRY_UNREADABLE)
        if stop is not None and halt_covers(stop, client):
            return stop
    return None


def halt_main_root(repo_root):
    """The main worktree of the linked worktree at `repo_root` (its `.git` is a file naming a gitdir whose
    `commondir` leads to the main `.git`), or the bare repository itself that holds it, else None. Read from
    disk: the runtime cannot wait on git."""
    dot = Path(repo_root) / ".git"
    try:
        text = dot.read_text(encoding="utf-8").strip() if dot.is_file() else ""
        if not text.startswith(_HALT_GITDIR):
            return None
        gitdir = Path(repo_root) / text[len(_HALT_GITDIR) :].strip()  # an absolute gitdir replaces the root
        common = gitdir.joinpath("commondir").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None  # a submodule's gitdir has no commondir: it is no linked worktree
    common_dir = Path(os.path.realpath(gitdir / common))
    return common_dir.parent if common_dir.name == ".git" else common_dir


def halt_repos(path):
    """Every repository holding `path`, as spelled and with every symlink resolved, nearest first: each folder up
    from it with a `.git`, nested ones included."""
    try:
        text = str(path)
        heres = dict.fromkeys(Path(found) for found in (os.path.abspath(text), os.path.realpath(text)))
    except (OSError, ValueError):
        return []
    folders = (folder for here in heres for folder in (here, *here.parents))
    return [folder for folder in dict.fromkeys(folders) if os.path.lexists(folder / ".git")]


def halt_find(roots, client):
    """The first stop in force over `roots`, or in the main worktree of any of them, that reaches `client`."""
    seen = []
    for root in roots:
        for folder in (root, halt_main_root(root)):
            if folder is None or folder in seen:
                continue
            seen.append(folder)
            stop = halt_read(folder)
            if stop is not None and halt_covers(stop, client):
                return stop
    return None


def _halt_client(name):
    return str(name or "").strip().lower().replace("-", "_")


def _halt_names(client, named):
    """Whether `client` (from a marker or a bundle) names the client id `named`, or a shorter form of it."""
    return client.startswith(named) or named.startswith(client + "_")


def halt_covers(stop, client):
    """Whether `stop` reaches `client`: every agent, or the one named (`cursor_agent` is `cursor`'s; `codex` may
    be `codex_cli`). An agent naming no client, or one no in-agent client id matches, is reached: fail closed."""
    scope, client = _halt_client(stop.get("scope")), _halt_client(client)
    if scope == HALT_ALL or not client:
        return True
    return _halt_names(client, scope) or not any(_halt_names(client, known) for known in HALT_CLIENTS)


def halt_message(stop):
    """`stopped: <reason>`, the reason printable and capped, and the one way to lift it."""
    reason = "".join(ch for ch in str(stop.get("reason") or "") if ch.isprintable()).strip()
    reason = (reason or _HALT_NO_REASON)[:_HALT_REASON_CAP]
    if stop.get("everywhere"):
        return (
            f"{HALT_REASON}: {reason}. A person stopped every agent on this machine (`chock stop --everywhere`); "
            "every tool call is refused until they run `chock resume --everywhere`."
        )
    return (
        f"{HALT_REASON}: {reason}. A person stopped agents in this repository (`chock stop`); "
        "every tool call is refused until they run `chock resume`."
    )


def halt_git_roots(repo_root: Path) -> list[Path]:
    """Every folder whose stop reaches a git command, as the git dispatcher finds them: the work tree
    (`GIT_WORK_TREE` too), the checkout of the git dir and of the common dir (a bare repository is its own),
    and every folder above each, symlinks resolved."""
    named = [
        Path(repo_root),
        *(Path(os.environ[name]) for name in ("GIT_WORK_TREE", "GIT_DIR") if os.environ.get(name)),
    ]
    try:
        shown = subprocess.run(
            ["git", "rev-parse", "--absolute-git-dir", "--git-common-dir"],  # noqa: S607
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
        dirs = shown.stdout.splitlines() if shown.returncode == 0 else []
    except (OSError, subprocess.SubprocessError, UnicodeError):
        dirs = []
    for found in (Path(os.path.realpath(line)) for line in dirs if line):
        named.append(found.parent if found.name == ".git" else found)
    heres = (Path(spelled(str(path))) for path in named for spelled in (os.path.abspath, os.path.realpath))
    return list(dict.fromkeys(folder for here in heres for folder in (here, *here.parents)))

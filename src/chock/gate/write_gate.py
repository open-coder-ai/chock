"""Run a compiled gate against what an agent is writing, and say what it found.

The shell-command sibling of this is guard_runner: a policy whose check is a bash script,
gating a command. This is the declarative half -- a policy whose check is a compiled gate,
gating file content. Both are extracted into the vendored per-agent runtime, so both are
stdlib-only and neither may import chock.

Nothing here judges anything. The judging is the gate runner's, the same runner the git hook
invokes, so a policy cannot mean one thing at commit and another in the session.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

from .edit_image import added_from_event, edited_text
from .outside_repo import judged_files, outside_globs
from .patch_image import patch_added, patched_files
from .session_log import session_for

GATE_FLAG = "--gate"

_GATE_TIMEOUT_SECONDS = 30

#: A compiled gate sits at <root>/.chock/compiled/<id>/<surface>/gate.json, so the root is
#: four parents up and the vendored runner is its sibling. Derived rather than searched for:
#: a walk upwards could find a different repository's .chock on a nested checkout.
_GATE_DEPTH_TO_CHOCK = 3
_RUNNER_PARTS = ("bin", "gate.py")
#: A plugin package lays the runner beside its gate instead; the repository root is then the
#: agent's working directory, which the event carries.
_PACKAGED_RUNNER = "gate.py"

_GIT = "git"
#: git speaks UTF-8 whatever the console code page; a path that is not UTF-8 survives the round trip.
_UTF8 = "utf-8"
_PATH_ERRORS = "surrogateescape"
_PARENT = ".."
#: A Windows root is spelled with a drive (`C:`), which a POSIX root never is.
_DRIVE_COLON = ":"
#: git status codes: a deletion leaves no content to judge, a rename is followed by its old path.
_DELETED = "D"
_RENAMED = "R"

GATE_BLOCKED = "blocked"
GATE_CLEAN = "clean"
GATE_ERRORED = "errored"

VERDICT_DENY = "deny"


def gate_path_from_argv(argv):
    """The `--gate <path>` argument a vendored runtime was invoked with, or None."""
    if GATE_FLAG in argv:
        index = argv.index(GATE_FLAG)
        if index + 1 < len(argv):
            return Path(argv[index + 1])
    return None


def runner_for(gate):
    """The gate runner: beside the gate in a plugin, under .chock/bin in a repository, else None."""
    packaged = gate.resolve().parent / _PACKAGED_RUNNER
    if packaged.exists():
        return packaged
    parents = gate.resolve().parents
    if len(parents) <= _GATE_DEPTH_TO_CHOCK:
        return None
    runner = parents[_GATE_DEPTH_TO_CHOCK].joinpath(*_RUNNER_PARTS)
    return runner if runner.exists() else None


def writes_from_event(event, root=None):
    """The one file this tool call would write, or none when it carries no file text.

    An edit call carries only the text it inserts; judged alone, that fragment has no imports,
    no class and no neighbours, so a gate that reads a whole file (a script kind) finds nothing
    in it. An edit is therefore judged as the file it would leave: the file on disk with the
    call's replacements applied. When that cannot be rebuilt -- the file is unreadable, or the
    text to replace is not in it, so the call itself will fail -- the fragment is judged as
    before and the turn's end judges what actually landed. A Codex apply_patch call names its
    files only inside the patch; each one it adds or updates is judged as the patch leaves it.
    """
    patched = patched_files(event, root)
    if patched:
        return patched
    path = getattr(event, "path", None)
    content = getattr(event, "content", None)
    edited = edited_text(event, root)
    if path and edited is not None:
        return {str(path): edited}
    if not path or not isinstance(content, str):
        return {}
    return {str(path): content}


def _folded(pure):
    """`pure` with `..` folded lexically; an absolute path never climbs above its anchor."""
    parts = []
    for part in pure.parts:
        if part != _PARENT:
            parts.append(part)
        elif len(parts) > 1:
            parts.pop()
    return type(pure)(*parts)


def repo_relative(path, root):
    """`path` relative to `root` in POSIX form, as scope globs are written; as given when outside `root`."""
    text = str(path)
    if root is None:
        return text
    windows = os.name == "nt" or str(root)[1:2] == _DRIVE_COLON
    flavour = PureWindowsPath if windows else PurePosixPath
    try:
        return _folded(flavour(str(root)) / text).relative_to(flavour(str(root))).as_posix()
    except ValueError:
        pass
    if windows != (os.name == "nt"):
        return text
    try:
        return Path(root, text).resolve().relative_to(Path(root).resolve()).as_posix()
    except (OSError, ValueError, RuntimeError):
        return text


def repo_paths(path, root):
    """Every repo-relative name a write is judged under: as written, and through symlinks and case."""
    lexical = repo_relative(path, root)
    if root is None or (str(root)[1:2] == _DRIVE_COLON) != (os.name == "nt"):
        return (lexical,)
    try:
        resolved = Path(root, str(path)).resolve().relative_to(Path(root).resolve()).as_posix()
    except (OSError, ValueError, RuntimeError):
        return (lexical,)
    return tuple(dict.fromkeys((lexical, resolved)))


def changed_paths(repo_root):
    """Every uncommitted path in the worktree. Outside a repository there is nothing to list."""
    try:
        proc = subprocess.run(  # noqa: S603 -- enumerating the worktree is this function's job
            [_GIT, "-C", str(repo_root), "status", "--porcelain=v1", "--untracked-files=all", "-z"],
            capture_output=True,
            text=True,
            encoding=_UTF8,
            errors=_PATH_ERRORS,
            timeout=_GATE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    fields = [field for field in (proc.stdout or "").split("\0") if field]
    paths = []
    skip_next = False
    for field in fields:
        if skip_next:
            skip_next = False
            continue
        status, path = field[:2], field[3:]
        skip_next = status.startswith(_RENAMED)
        if _DELETED in status or not path:
            continue
        paths.append(path)
    return paths


def writes_from_worktree(repo_root):
    """What this turn actually left on disk, however it was written.

    The write path sees only writes it recognises; a shell heredoc carries no file argument.
    Reading final state is what makes that stop mattering, so this deliberately does not care
    which tool produced the bytes.
    """
    writes = {}
    for path in changed_paths(repo_root):
        try:
            writes[path] = Path(repo_root, path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    return writes


def run_gate(gate, writes, event, root=None, extra=None):
    """Ask the vendored runner. Returns (outcome, message) and never decides for itself.

    `extra` adds stdin keys: `added` (per edited path, only the text the edit introduces; a runner
    that predates it judges the whole file, which only ever refuses more) and the script `session`.
    """
    runner = runner_for(gate)
    if runner is None:
        return GATE_ERRORED, "the vendored gate runner is not installed beside this gate"
    try:
        proc = subprocess.run(  # noqa: S603 -- invoking the vendored runner is this function's job
            [sys.executable, str(runner), "run", "--gate", str(gate), "--event", event],
            input=json.dumps({"writes": writes, **(extra or {})}),
            capture_output=True,
            text=True,
            encoding=_UTF8,
            errors="replace",
            timeout=_GATE_TIMEOUT_SECONDS,
            check=False,
            cwd=str(root) if root is not None else None,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return GATE_ERRORED, str(exc)
    if proc.returncode == 0:
        return GATE_CLEAN, ""
    if proc.returncode == 1:
        return GATE_BLOCKED, (proc.stderr or "").strip()
    return GATE_ERRORED, (proc.stderr or "").strip()


#: The canonical event names agentseam's contract uses, mapped to the runner's own spelling.
#: Written as literals because the bundle defines the constants and this module must not
#: import agentseam to reach them.
_EVENT_ARG = {"pre_tool": "pre-tool-use", "stop": "stop"}

PRE_TOOL = "pre_tool"


def root_for(gate):
    """The repository this compiled gate belongs to, or None when the layout is not that."""
    parents = gate.resolve().parents
    if len(parents) <= _GATE_DEPTH_TO_CHOCK:
        return None
    if parents[_GATE_DEPTH_TO_CHOCK - 1].name != "compiled" or parents[_GATE_DEPTH_TO_CHOCK].name != ".chock":
        return None
    return parents[_GATE_DEPTH_TO_CHOCK].parent


def repo_root_for(event, gate):
    """The repository under judgement: the compiled layout's root, else where the agent works."""
    root = root_for(gate)
    if root is not None:
        return root
    cwd = getattr(event, "cwd", None)
    return Path(cwd) if cwd else Path.cwd()


def writes_for(event, gate):
    """What this event puts under judgement: the call's own text, or what the turn left behind."""
    if event.event == PRE_TOOL:
        return writes_from_event(event, repo_root_for(event, gate))
    if _reentered(event):
        return {}
    return writes_from_worktree(repo_root_for(event, gate))


def _reentered(event):
    """Whether this stop re-entered its own hook: Claude Code's `stop_hook_active`, Cursor's `loop_count`."""
    # A refusal that re-entered its own stop hook would never terminate.
    raw = event.raw or {}
    return bool(raw.get("stop_hook_active") or raw.get("loop_count"))


def _missing_gate(gate, event):
    """A gate the hook names but that is not on disk: a broken install, so a refusal that says so."""
    if event.event != PRE_TOOL and _reentered(event):
        return None
    return (
        VERDICT_DENY,
        f"chock gate {gate} is missing, so this write cannot be checked. "
        "Run `chock sync --repo .` to rebuild the compiled gates.",
    )


def evaluate_gate(argv, event):
    """The decision this event earns from a compiled gate, or None when it has nothing to say."""
    gate = gate_path_from_argv(argv)
    name = _EVENT_ARG.get(getattr(event, "event", ""))
    if gate is None or name is None:
        return None
    if not gate.exists():
        return _missing_gate(gate, event)
    root = repo_root_for(event, gate)
    outside = outside_globs(gate)
    writes = judged_files(writes_for(event, gate), root, outside, lambda path: repo_paths(path, root))
    if not writes:
        return None
    added = {**patch_added(event), **added_from_event(event)} if event.event == PRE_TOOL else {}
    added = judged_files(added, root, outside, lambda path: repo_paths(path, root))
    added = {path: text for path, text in added.items() if path in writes}
    extra = {**({"added": added} if added else {}), "session": session_for(event, root)}
    outcome, message = run_gate(gate, writes, name, root, extra)
    if outcome == GATE_BLOCKED:
        return (VERDICT_DENY, message or f"Blocked by chock policy: {gate.parent.parent.name}")
    if outcome == GATE_ERRORED:
        return (
            VERDICT_DENY,
            f"chock could not check this write: {message}. Refusing rather than reporting an "
            "allow it never established.",
        )
    return None

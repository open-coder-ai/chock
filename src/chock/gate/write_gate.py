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
import subprocess
import sys
from pathlib import Path

from .edit_image import added_from_event, edited_text

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
    before and the turn's end judges what actually landed.
    """
    path = getattr(event, "path", None)
    content = getattr(event, "content", None)
    edited = edited_text(event, root)
    if path and edited is not None:
        return {str(path): edited}
    if not path or not isinstance(content, str):
        return {}
    return {str(path): content}


def changed_paths(repo_root):
    """Every uncommitted path in the worktree. Outside a repository there is nothing to list."""
    try:
        proc = subprocess.run(  # noqa: S603 -- enumerating the worktree is this function's job
            [_GIT, "-C", str(repo_root), "status", "--porcelain=v1", "--untracked-files=all", "-z"],
            capture_output=True,
            text=True,
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


def run_gate(gate, writes, event, root=None, added=None):
    """Ask the vendored runner. Returns (outcome, message) and never decides for itself.

    `added` carries, per edited path, only the text the edit introduces: a kind that reads
    added lines judges that, while a kind that reads the file judges `writes`. A runner that
    predates the key ignores it and judges the whole file for both, which only ever refuses more.
    """
    runner = runner_for(gate)
    if runner is None:
        return GATE_ERRORED, "the vendored gate runner is not installed beside this gate"
    try:
        proc = subprocess.run(  # noqa: S603 -- invoking the vendored runner is this function's job
            [sys.executable, str(runner), "run", "--gate", str(gate), "--event", event],
            input=json.dumps({"writes": writes, **({"added": added} if added else {})}),
            capture_output=True,
            text=True,
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
    raw = event.raw or {}
    if raw.get("stop_hook_active") or raw.get("loop_count"):
        # A refusal that re-entered its own stop hook would never terminate: Claude Code marks
        # the re-entry `stop_hook_active`, Cursor counts it in `loop_count`.
        return {}
    return writes_from_worktree(repo_root_for(event, gate))


def evaluate_gate(argv, event):
    """The decision this event earns from a compiled gate, or None when it has nothing to say."""
    gate = gate_path_from_argv(argv)
    name = _EVENT_ARG.get(getattr(event, "event", ""))
    if gate is None or name is None or not gate.exists():
        return None
    writes = writes_for(event, gate)
    if not writes:
        return None
    added = added_from_event(event) if event.event == PRE_TOOL else {}
    added = {path: text for path, text in added.items() if path in writes}
    outcome, message = run_gate(gate, writes, name, repo_root_for(event, gate), added)
    if outcome == GATE_BLOCKED:
        return (VERDICT_DENY, message or f"Blocked by chock policy: {gate.parent.parent.name}")
    if outcome == GATE_ERRORED:
        return (
            VERDICT_DENY,
            f"chock could not check this write: {message}. Refusing rather than reporting an "
            "allow it never established.",
        )
    return None

"""Per-agent vendored runtime: agentseam's bundle() plus chock's own gate handler.

`.chock/bin/pretooluse.py` used to be one hand-written, cross-vendor file that sniffed
which client sent a payload by its shape (`is_cursor_payload`, `is_codex_payload`) and
spoke each dialect back inline. agentseam now ships exactly the plumbing that sniffing
existed to approximate -- a real, per-agent adapter, live-verified against each vendor --
via `bundler.bundle(agent)`: normalized stdin parsing, the degrade-to-what-this-agent-can-
honor step, and the vendor-specific response dialect, all in one self-contained,
stdlib-only file with a `handle(event)` stub fenced between marker comments.

This module renders that file for the agents chock actually gates (`RUNTIME_AGENTS`):
agentseam's plumbing, chock's `handle()` spliced into the marker block. The handler's own
logic is source-extracted (the same technique agentseam's own bundler uses to pull one
module's names into another) from real, separately-importable chock modules --
`gate.guard_runner` (used as-is by `eval/execute.py`) and `gate.sessionstart` (the
git-hook-arming logic, folded in only for claude_code's SessionStart branch) -- so the
vendored copy can never drift from the code chock itself runs and tests.
"""

from __future__ import annotations

import ast
import inspect

from agentseam import bundler

from . import guard_runner, sessionstart

BEGIN = "# >>> agentseam handler >>>"
END = "# <<< agentseam handler <<<"

#: Only claude_code's vendored runtime also arms git hooks at session start (the fragment
#: is installed only into `.claude/settings.json`'s SessionStart key -- no other surface
#: chock installs a SessionStart hook on). Every other agent's bundle only ever sees
#: pre_tool.
_SESSION_START_AGENTS = frozenset({"claude_code"})

#: Agents chock renders a vendored runtime for. Matches `compile.surfaces.SURFACE_AGENTS`'
#: PRE_TOOL_USE (claude, cursor) and AGENT_HOOKS (copilot, vscode -> vscode_copilot)
#: membership, plus codex_cli: `gate/pretooluse.py` has long recognized (and tested) a
#: Codex-shaped payload defensively even though chock has never shipped an automatic Codex
#: PreToolUse installer, because a hand-wired Codex hook pointed at the same adapter path
#: is a real, supported (if manual) adoption path. Dropping that dialect here would be a
#: silent regression for anyone relying on it.
RUNTIME_AGENTS = ("claude_code", "codex_cli", "cursor", "vscode_copilot")

_IMPORTS = """\
import os as _chock_os
import shlex as _chock_shlex
import subprocess as _chock_subprocess
from datetime import datetime as _chock_datetime, timezone as _chock_timezone
from pathlib import Path as _chock_Path
"""

#: Every name `guard_runner`/`sessionstart` reference that this splice must rename so it
#: cannot collide with a name agentseam's own bundle sections define, and so the imports
#: above (aliased `_chock_*`, matching this project's other vendored files) are what the
#: extracted bodies actually use.
_RENAME = {
    "os": "_chock_os",
    "shlex": "_chock_shlex",
    "subprocess": "_chock_subprocess",
    "datetime": "_chock_datetime",
    "timezone": "_chock_timezone",
    "Path": "_chock_Path",
}


class _Renamer(ast.NodeTransformer):
    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id in _RENAME:
            node.id = _RENAME[node.id]
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        self.generic_visit(node)
        return node


def _extract(module) -> str:
    """Every top-level def/assignment in `module`, source order, minus its own imports --
    the same shape `agentseam.bundler._extract_with_deps` pulls out of ITS source modules,
    applied to chock's own."""
    source = inspect.getsource(module)
    tree = ast.parse(source)
    segments = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign)):
            segments.append(_Renamer().visit(ast.parse(ast.get_source_segment(source, node))))
    return "\n\n".join(ast.unparse(seg) for seg in segments) + "\n"


_DISPATCH = """\


def handle(event):
    if event.event == "pre_tool" and event.command:
        reason = evaluate(sys.argv[1:], event.command, event.tool or "")
        return Decision.deny(reason) if reason else None
{session_start_branch}    return None
"""

_SESSION_START_BRANCH = """\
    if event.event == "session_start":
        return _chock_handle_session_start(event)
"""

_SESSION_START_ORCHESTRATION = """\


def _chock_handle_session_start(event):
    repo_root = _repo_root()
    if not (repo_root / ".chock").is_dir():
        return None  # not a chock-managed repo
    if _armed(repo_root):
        return None

    if _chock_importable():
        try:
            proc = _chock_subprocess.run(
                [sys.executable, "-m", "chock", "sync", "--repo", str(repo_root)],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=240,
            )
        except (OSError, _chock_subprocess.TimeoutExpired):
            proc = None
        if proc is not None and proc.returncode == 0 and _armed(repo_root):
            return Decision.allow(
                context=(
                    "Chock: this clone's git hooks were not installed (git never clones hooks); "
                    "armed them now with `chock sync`."
                )
            )

    return Decision.allow(context=_INSTRUCTION)
"""


def _handler_source(agent: str) -> str:
    """The full handler-block body for `agent`: extracted guard logic, optionally extracted
    session-start logic, then `handle()` dispatching between them. `_IMPORTS` is NOT here --
    a module-level import this deep in the file is a style violation (E402), so `render()`
    hoists it to the top instead, right after the bundle's own `import json` / `import sys`."""
    parts = [_extract(guard_runner)]
    if agent in _SESSION_START_AGENTS:
        parts.append("\n")
        parts.append(_extract(sessionstart))
        parts.append(_SESSION_START_ORCHESTRATION)
    parts.append(_DISPATCH.format(session_start_branch=_SESSION_START_BRANCH if agent in _SESSION_START_AGENTS else ""))
    return "".join(parts)


#: The exact text `bundler.bundle()` writes right after its HEADER comment (see
#: `bundler.py`'s `sections[1]`) -- the anchor `render()` hoists `_IMPORTS` after, so every
#: import in the rendered file sits at the top, before any def/class/assignment.
_TOP_IMPORTS_ANCHOR = "from __future__ import annotations\n\nimport json\nimport sys\n"


def render(agent: str) -> str:
    """Render `agent`'s self-contained vendored runtime: agentseam's bundle, chock's
    handler spliced into the marker block agentseam leaves for exactly this."""
    source = bundler.bundle(agent)
    if _TOP_IMPORTS_ANCHOR not in source:
        raise ValueError("%s: bundle() output has no top-imports anchor to hoist onto" % agent)
    source = source.replace(_TOP_IMPORTS_ANCHOR, _TOP_IMPORTS_ANCHOR + "\n" + _IMPORTS, 1)
    head, sep, rest = source.partition(BEGIN)
    if not sep:
        raise ValueError("%s: bundle() output has no %r marker" % (agent, BEGIN))
    _, sep2, tail = rest.partition(END)
    if not sep2:
        raise ValueError("%s: bundle() output has no %r marker" % (agent, END))
    return "%s%s\n%s%s%s" % (head, BEGIN, _handler_source(agent), END, tail)

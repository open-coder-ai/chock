"""Per-agent vendored runtime: agentseam's bundle() plus chock's own gate handler."""

from __future__ import annotations

import ast
import inspect

from agentseam import bundler

from . import guard_runner, sessionstart

BEGIN = "# >>> agentseam handler >>>"
END = "# <<< agentseam handler <<<"

_SESSION_START_AGENTS = frozenset({"claude_code"})

RUNTIME_AGENTS = ("claude_code", "codex_cli", "cursor", "vscode_copilot")

_IMPORTS = """\
import os as _chock_os
import shlex as _chock_shlex
import subprocess as _chock_subprocess
from datetime import datetime as _chock_datetime, timezone as _chock_timezone
from pathlib import Path as _chock_Path
"""

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
    """Every top-level def/assignment in `module`, source order, minus its own imports --"""
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
        verdict = evaluate(sys.argv[1:], event.command, event.tool or "")
        if verdict is not None:
            outcome, reason = verdict
            return Decision.escalate(reason) if outcome == ESCALATE else Decision.deny(reason)
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
    """The full handler-block body for `agent`: extracted guard logic, optionally extracted"""
    parts = [_extract(guard_runner)]
    if agent in _SESSION_START_AGENTS:
        parts.append("\n")
        parts.append(_extract(sessionstart))
        parts.append(_SESSION_START_ORCHESTRATION)
    parts.append(_DISPATCH.format(session_start_branch=_SESSION_START_BRANCH if agent in _SESSION_START_AGENTS else ""))
    return "".join(parts)


_TOP_IMPORTS_ANCHOR = "from __future__ import annotations\n\nimport json\n_json = json\nimport sys\n"


def render(agent: str) -> str:
    """Render `agent`'s self-contained vendored runtime: agentseam's bundle, chock's"""
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

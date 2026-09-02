"""Per-agent vendored runtime: agentseam's bundle() plus chock's own gate handler."""

from __future__ import annotations

import ast
import inspect

from agentseam import bundler

from chock.resources import template_text
from chock.vendors import in_agent_vendors

from . import guard_runner, sessionstart

BEGIN = "# >>> agentseam handler >>>"
END = "# <<< agentseam handler <<<"

_SESSION_START_AGENTS = frozenset({"claude_code"})

RUNTIME_AGENTS = in_agent_vendors()

# Templates carry their exact emitted bytes, leading blank lines included.
_IMPORTS = template_text("runtime/imports.py.tmpl")

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


_DISPATCH = template_text("runtime/dispatch.py.tmpl")
_DISPATCH_SESSION_START = template_text("runtime/dispatch-session-start.py.tmpl")
_SESSION_START_ORCHESTRATION = template_text("runtime/session-start-orchestration.py.tmpl")


def _handler_source(agent: str) -> str:
    """The full handler-block body for `agent`: extracted guard logic, optionally extracted"""
    parts = [_extract(guard_runner)]
    if agent in _SESSION_START_AGENTS:
        parts.append("\n")
        parts.append(_extract(sessionstart))
        parts.append(_SESSION_START_ORCHESTRATION)
    parts.append(_DISPATCH_SESSION_START if agent in _SESSION_START_AGENTS else _DISPATCH)
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

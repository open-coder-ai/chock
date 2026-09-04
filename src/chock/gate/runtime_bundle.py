"""Per-agent vendored runtime: agentseam's bundle() plus chock's own gate handler."""

from __future__ import annotations

import ast
import inspect
import re

from agentseam import bundler

from chock.resources import package_data_dir
from chock.vendors import in_agent_vendors

from . import guard_runner, sessionstart

BEGIN = "# >>> agentseam handler >>>"
END = "# <<< agentseam handler <<<"

_SESSION_START_AGENTS = frozenset({"claude_code"})

RUNTIME_AGENTS = in_agent_vendors()

_DATA_DIR = package_data_dir("chock.gate", "data")
_IMPORTS = _DATA_DIR.joinpath("imports.py.tmpl").read_text(encoding="utf-8")

_RENAME = {
    "os": "_chock_os",
    "shlex": "_chock_shlex",
    "shutil": "_chock_shutil",
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


_DISPATCH = _DATA_DIR.joinpath("dispatch.py.tmpl").read_text(encoding="utf-8")
_DISPATCH_BRANCH_TOKEN = "# __SESSION_START_BRANCH__\n"  # noqa: S105 -- a template marker, not a credential

_SESSION_START_BRANCH = _DATA_DIR.joinpath("session_start_branch.py.tmpl").read_text(encoding="utf-8")

_SESSION_START_ORCHESTRATION = _DATA_DIR.joinpath("session_start_orchestration.py.tmpl").read_text(encoding="utf-8")


def _handler_source(agent: str) -> str:
    """The full handler-block body for `agent`: extracted guard logic, optionally extracted"""
    parts = [_extract(guard_runner)]
    if agent in _SESSION_START_AGENTS:
        parts.append("\n")
        parts.append(_extract(sessionstart))
        parts.append(_SESSION_START_ORCHESTRATION)
    branch = _SESSION_START_BRANCH if agent in _SESSION_START_AGENTS else ""
    parts.append(_DISPATCH.replace(_DISPATCH_BRANCH_TOKEN, branch))
    return "".join(parts)


_TOP_IMPORTS_ANCHOR = "from __future__ import annotations\n\nimport json\n_json = json\nimport sys\n"


def _needed_imports(handler_source: str) -> str:
    """`_IMPORTS`, minus any line whose renamed name(s) `handler_source` never references.

    `_IMPORTS` is one fixed block spliced into every vendor's bundle, but `guard_runner`
    (extracted for every vendor) uses only five of its six names -- `shutil` is used solely by
    `sessionstart`, extracted for claude_code alone, so every other vendor's bundle carried a
    dead import. Filtering per line against what the assembled handler actually uses keeps
    this in sync as the handler modules change, rather than hand-tuning the template.
    """
    used = set(re.findall(r"_chock_\w+", handler_source))
    lines = [line for line in _IMPORTS.splitlines() if used & set(re.findall(r"_chock_\w+", line))]
    return "\n".join(lines) + ("\n" if lines else "")


def render(agent: str) -> str:
    """Render `agent`'s self-contained vendored runtime: agentseam's bundle, chock's"""
    source = bundler.bundle(agent)
    if _TOP_IMPORTS_ANCHOR not in source:
        raise ValueError("%s: bundle() output has no top-imports anchor to hoist onto" % agent)
    handler = _handler_source(agent)
    source = source.replace(_TOP_IMPORTS_ANCHOR, _TOP_IMPORTS_ANCHOR + "\n" + _needed_imports(handler), 1)
    head, sep, rest = source.partition(BEGIN)
    if not sep:
        raise ValueError("%s: bundle() output has no %r marker" % (agent, BEGIN))
    _, sep2, tail = rest.partition(END)
    if not sep2:
        raise ValueError("%s: bundle() output has no %r marker" % (agent, END))
    return "%s%s\n%s%s%s" % (head, BEGIN, handler, END, tail)

"""Per-agent vendored runtime: agentseam's bundle() plus chock's own gate handler."""

from __future__ import annotations

import ast
import functools
import inspect
import re

from agentseam import bundler

from chock.resources import package_data_dir
from chock.vendors import in_agent_vendors

from . import edit_image, gate_outcome, guard_runner, patch_image, sessionstart, write_gate

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
    "PurePosixPath": "_chock_PurePosixPath",
    "PureWindowsPath": "_chock_PureWindowsPath",
}


class _Renamer(ast.NodeTransformer):
    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id in _RENAME:
            node.id = _RENAME[node.id]
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        self.generic_visit(node)
        return node


def _segment(lines: list[bytes], node: ast.stmt) -> str:
    """`ast.get_source_segment` over lines split once: it re-splits the whole source on every call."""
    chunk = lines[node.lineno - 1 : node.end_lineno]
    chunk[-1] = chunk[-1][: node.end_col_offset]
    chunk[0] = chunk[0][node.col_offset :]
    return b"".join(chunk).decode("utf-8")


@functools.cache
def _extract(module) -> str:
    """Every top-level def/assignment in `module`, source order, minus its own imports --"""
    source = inspect.getsource(module)
    tree = ast.parse(source)
    lines = source.encode("utf-8").splitlines(keepends=True)  # bytes split on \r, \n only, as ast counts lines
    segments = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign)):
            segments.append(_Renamer().visit(ast.parse(_segment(lines, node))))
    return "\n\n".join(ast.unparse(seg) for seg in segments) + "\n"


_DISPATCH = _DATA_DIR.joinpath("dispatch.py.tmpl").read_text(encoding="utf-8")
_DISPATCH_BRANCH_TOKEN = "# __SESSION_START_BRANCH__\n"  # noqa: S105 -- a template marker, not a credential

_SESSION_START_BRANCH = _DATA_DIR.joinpath("session_start_branch.py.tmpl").read_text(encoding="utf-8")

_SESSION_START_ORCHESTRATION = _DATA_DIR.joinpath("session_start_orchestration.py.tmpl").read_text(encoding="utf-8")

#: Vendors whose refusal also carries the top-level answer their runtime was witnessed honouring.
_COPILOT_RESPOND_AGENTS = frozenset({"vscode_copilot"})
#: agentseam's own call, in `_decide`, that the Copilot answer is routed through instead: a rebind of
#: `respond` would shadow its name in the one flat namespace, which test_runtime_goldens forbids.
_RESPOND_CALL = "return respond(degrade(decision, event), event)"
_COPILOT_RESPOND_CALL = "return _chock_copilot_respond(degrade(decision, event), event)"
_COPILOT_RESPOND = _DATA_DIR.joinpath("copilot_respond.py.tmpl").read_text(encoding="utf-8")


#: Vendors whose warn also reaches the agent or the user: only where the reply channel is documented.
_WARN_RESPOND_AGENTS = frozenset({"claude_code"})
_WARN_RESPOND_CALL = "return _chock_warn_respond(degrade(decision, event), event)"
_WARN_RESPOND = _DATA_DIR.joinpath("warn_respond.py.tmpl").read_text(encoding="utf-8")


def _handler_source(agent: str) -> str:
    """The full handler-block body for `agent`: extracted guard logic, optionally extracted"""
    parts = [
        _extract(guard_runner),
        "\n",
        _extract(edit_image),
        "\n",
        _extract(patch_image),
        "\n",
        _extract(gate_outcome),
        "\n",
        _extract(write_gate),
    ]
    if agent in _SESSION_START_AGENTS:
        parts.append("\n")
        parts.append(_extract(sessionstart))
        parts.append(_SESSION_START_ORCHESTRATION)
    branch = _SESSION_START_BRANCH if agent in _SESSION_START_AGENTS else ""
    parts.append(_DISPATCH.replace(_DISPATCH_BRANCH_TOKEN, branch))
    if agent in _COPILOT_RESPOND_AGENTS:
        parts.append(_COPILOT_RESPOND)
    if agent in _WARN_RESPOND_AGENTS:
        parts.append(_WARN_RESPOND)
    return "".join(parts)


_FUTURE = "from __future__ import annotations\n\n"

#: chock's imports go right after this line of agentseam's hoisted block. Anchored on the one
#: line, not the whole block: agentseam 0.3.4 hoists contextlib/io/os around json and sys, and
#: an exact-block anchor then matched nothing -- every runtime failed to render and sync wired
#: no hooks at all. Where the block is unchanged the output is byte-identical to before.
_SYS_IMPORT = "import sys\n"


def _hoist_point(source: str) -> int:
    """Offset just past `import sys` in the import block after `from __future__`, or -1."""
    start = source.find(_FUTURE)
    if start < 0:
        return -1
    block_start = start + len(_FUTURE)
    block_end = source.find("\n\n", block_start)
    block = source[block_start : block_end + 1 if block_end >= 0 else len(source)]
    at = ("\n" + block).find("\n" + _SYS_IMPORT)
    return -1 if at < 0 else block_start + at + len(_SYS_IMPORT)


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


@functools.cache
def render(agent: str) -> str:
    """Render `agent`'s self-contained vendored runtime: agentseam's bundle, chock's"""
    source = bundler.bundle(agent)
    at = _hoist_point(source)
    if at < 0:
        raise ValueError("%s: bundle() output has no top-imports anchor to hoist onto" % agent)
    handler = _handler_source(agent)
    source = source[:at] + "\n" + _needed_imports(handler) + source[at:]
    head, sep, rest = source.partition(BEGIN)
    if not sep:
        raise ValueError("%s: bundle() output has no %r marker" % (agent, BEGIN))
    _, sep2, tail = rest.partition(END)
    if not sep2:
        raise ValueError("%s: bundle() output has no %r marker" % (agent, END))
    if agent in _COPILOT_RESPOND_AGENTS:
        if _RESPOND_CALL not in tail:
            raise ValueError("%s: bundle() output has no %r call to route" % (agent, _RESPOND_CALL))
        tail = tail.replace(_RESPOND_CALL, _COPILOT_RESPOND_CALL)
    if agent in _WARN_RESPOND_AGENTS:
        if _RESPOND_CALL not in tail:
            raise ValueError("%s: bundle() output has no %r call to route" % (agent, _RESPOND_CALL))
        tail = tail.replace(_RESPOND_CALL, _WARN_RESPOND_CALL)
    return "%s%s\n%s%s%s" % (head, BEGIN, handler, END, tail)

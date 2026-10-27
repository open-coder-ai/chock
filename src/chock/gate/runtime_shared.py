"""The shared runtime every per-agent entry loads: chock's guard modules, extracted into one stdlib-only file."""

from __future__ import annotations

import ast
import functools
import hashlib
import inspect
import re

from chock.resources import package_data_dir

from . import (
    budget,
    decision_log,
    decision_target,
    edit_image,
    gate_outcome,
    guard_runner,
    outside_repo,
    patch_apply,
    patch_image,
    repo_stop,
    session_log,
    stop_reentry,
    stop_roots,
    tool_call_gate,
    unreadable_stop,
    workspace_root,
    write_gate,
)
from .runner import chain, halt, journal

_DATA_DIR = package_data_dir("chock.gate", "data")
_IMPORTS = _DATA_DIR.joinpath("imports.py.tmpl").read_text(encoding="utf-8")

_RENAME = {
    "fnmatch": "_chock_fnmatch",
    "hashlib": "_chock_hashlib",
    "re": "_chock_re",
    "os": "_chock_os",
    "queue": "_chock_queue",
    "shlex": "_chock_shlex",
    "shutil": "_chock_shutil",
    "subprocess": "_chock_subprocess",
    "threading": "_chock_threading",
    "time": "_chock_time",
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

    def visit_JoinedStr(self, node: ast.JoinedStr) -> ast.AST:
        self.generic_visit(node)
        return _lower(node) if _has_string_literal(node) else node


_CONVERSIONS = {ord("s"): "str", ord("r"): "repr", ord("a"): "ascii"}


def _has_string_literal(node: ast.JoinedStr) -> bool:
    """True when a replacement field holds a string literal or a quote: the quotes `ast.unparse` picks for it depend on the interpreter."""
    for field in node.values:
        if not isinstance(field, ast.FormattedValue):
            continue
        if any(
            isinstance(inner, ast.Constant) and isinstance(inner.value, (str, bytes)) for inner in ast.walk(field.value)
        ):
            return True
        for part in field.format_spec.values if field.format_spec else ():
            quoted = isinstance(part, ast.Constant) and ("'" in part.value or '"' in part.value)
            if quoted or (isinstance(part, ast.FormattedValue) and _has_string_literal(ast.JoinedStr([part]))):
                return True
    return False


def _call(func: ast.expr, *args: ast.expr) -> ast.Call:
    return ast.Call(func=func, args=list(args), keywords=[])


def _lower(node: ast.JoinedStr) -> ast.expr:
    """`f"{', '.join(x)}"` as `''.join([format(', '.join(x))])`: no f-string quoting left to differ between 3.11 and 3.12.x."""
    parts: list[ast.expr] = []
    for field in node.values:
        if isinstance(field, ast.Constant):
            parts.append(field)
            continue
        value = field.value
        if field.conversion in _CONVERSIONS:
            value = _call(ast.Name(_CONVERSIONS[field.conversion], ast.Load()), value)
        spec = [_lower(field.format_spec)] if field.format_spec else []
        parts.append(_call(ast.Name("format", ast.Load()), value, *spec))
    if all(isinstance(part, ast.Constant) for part in parts):
        return ast.Constant("".join(part.value for part in parts))
    joiner = ast.Attribute(ast.Constant(""), "join", ast.Load())
    return ast.copy_location(_call(joiner, ast.List(parts, ast.Load())), node)


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


#: The modules every handler carries, in order: each may use the names of those before it.
_HANDLER_MODULES = (
    budget,
    chain,
    journal,
    halt,
    guard_runner,
    decision_target,
    decision_log,
    edit_image,
    patch_apply,
    patch_image,
    gate_outcome,
    outside_repo,
    session_log,
    stop_reentry,
    unreadable_stop,
    workspace_root,
    repo_stop,
    stop_roots,
    write_gate,
    tool_call_gate,
)


#: The one module every entry in a folder loads, beside it: the extracted `_HANDLER_MODULES`.
SHARED_NAME = "_chock_runtime"
SHARED_FILE = f"{SHARED_NAME}.py"
_SHARED = _DATA_DIR.joinpath("shared_runtime.py.tmpl").read_text(encoding="utf-8")


def _shared_body() -> str:
    """The guard logic every vendor's handler carries, identically: stdlib only, no vendor names."""
    return "\n".join(_extract(module) for module in _HANDLER_MODULES)


@functools.cache
def _shared() -> tuple[str, str]:
    """(shared runtime text, its pin): the sha256 of the bytes written to disk, which an entry hashes before it execs them."""
    body = _shared_body()
    text = _SHARED.replace("__IMPORTS__\n", _needed_imports(body)).replace("__BODY__\n", body)
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def render_shared() -> str:
    """The shared runtime every entry in a folder loads, as `SHARED_FILE` beside it."""
    return _shared()[0]


def shared_pin() -> str:
    """The sha256 of the shared runtime file every entry rendered now requires."""
    return _shared()[1]


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

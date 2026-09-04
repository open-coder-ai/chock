"""AST-based call-graph analysis over `src/`: what a function calls, and what severities a
`Report`-based check function can (transitively) produce.

Generic infrastructure, not itself matrix-specific -- `checks_matrix_mechanisms.py` (chock's
own 300-line file budget forced the split) is the module that reads matrix rows and asks this
one whether the row's claimed mechanism holds up.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_SEVERITY_WORDS = frozenset({"error", "warning", "info"})


@dataclass(frozen=True)
class Module:
    dotted: str
    tree: ast.Module


def module_dotted_name(src_root: Path, file: Path) -> str:
    parts = list(file.relative_to(src_root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def load_modules(src_root: Path) -> dict[str, Module]:
    modules: dict[str, Module] = {}
    for file in src_root.rglob("*.py"):
        if file.relative_to(src_root).parts[0] != "chock":
            continue
        try:
            tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        dotted = module_dotted_name(src_root, file)
        modules[dotted] = Module(dotted, tree)
    return modules


def _imported_modules(tree: ast.Module) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    return imported


def reachable_modules(modules: dict[str, Module], entry_points: Iterable[str]) -> set[str]:
    """BFS over the import graph from `entry_points` -- the union of both dispatch paths."""
    reachable: set[str] = set()
    queue = [m for m in entry_points if m in modules]
    while queue:
        dotted = queue.pop()
        if dotted in reachable:
            continue
        reachable.add(dotted)
        for imported in _imported_modules(modules[dotted].tree):
            if imported in modules and imported not in reachable:
                queue.append(imported)
    return reachable


def _call_target_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


@dataclass(frozen=True)
class FunctionSite:
    module: str
    node: ast.FunctionDef


@dataclass(frozen=True)
class CallGraph:
    #: function name -> every place it is defined.
    defs: dict[str, list[FunctionSite]]
    #: function name -> every module containing a call site for it.
    callers: dict[str, set[str]]


def build_call_graph(modules: dict[str, Module]) -> CallGraph:
    """One pass over every module's AST, instead of rescanning all of src/ per function name."""
    defs: dict[str, list[FunctionSite]] = {}
    callers: dict[str, set[str]] = {}
    for dotted, mod in modules.items():
        for node in ast.walk(mod.tree):
            if isinstance(node, ast.FunctionDef):
                defs.setdefault(node.name, []).append(FunctionSite(dotted, node))
            elif isinstance(node, ast.Call):
                name = _call_target_name(node)
                if name:
                    callers.setdefault(name, set()).add(dotted)
    return CallGraph(defs, callers)


def _direct_finding_severities(node: ast.AST) -> set[str]:
    """Every literal `"error"`/`"warning"`/`"info"` in the body, not just a `Finding(...)`'s 3rd arg.

    Most checks pass severity as a literal straight into `Finding(...)`, but some (SEC-4's
    `_scan_text_surfaces`) build a `(text, severity, ...)` tuple and pass the loop variable
    through instead. Scanning every string literal catches both without needing real dataflow
    analysis; chock's own convention never reuses these three words for anything else (check
    names and messages are longer / different strings), so this stays precise in practice.
    """
    return {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and n.value in _SEVERITY_WORDS}


def _called_function_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        name = _call_target_name(call)
        if name and name != "Finding":
            names.add(name)
    return names


def _transitive_report_severities(graph: CallGraph, node: ast.FunctionDef, seen: set[int]) -> set[str]:
    """Findings are often built by a helper the check calls, not inline (AMB-2's own pattern).

    Follows the call graph -- not just the target's own body -- so a check that delegates
    `Finding(...)` construction to a helper is still credited with the severities it produces.
    """
    if id(node) in seen:
        return set()
    seen.add(id(node))

    severities = _direct_finding_severities(node)
    for name in _called_function_names(node):
        for site in graph.defs.get(name, []):
            severities |= _transitive_report_severities(graph, site.node, seen)
    return severities


def _returns_nonzero(node: ast.FunctionDef) -> bool:
    return any(
        isinstance(ret, ast.Return)
        and isinstance(ret.value, ast.Constant)
        and isinstance(ret.value.value, int)
        and ret.value.value != 0
        for ret in ast.walk(node)
    )


def _achievable_severities(graph: CallGraph, node: ast.FunctionDef) -> set[str]:
    """A `report`-taking check can emit whatever severities it (transitively) builds `Finding`s with.

    A bare CLI entrypoint (no `report` parameter) has no such vocabulary -- it is binary, and
    within `chock check` a nonzero exit is indistinguishable from `error`; it cannot represent
    `warning`/`info`.
    """
    has_report_param = any(arg.arg == "report" for arg in node.args.args)
    if has_report_param:
        return _transitive_report_severities(graph, node, set())
    return {"error"} if _returns_nonzero(node) else set()


@dataclass(frozen=True)
class MechanismVerdict:
    exists: bool
    invoked: bool
    achievable: set[str]


def verify_mechanism(graph: CallGraph, reachable: set[str], name: str) -> MechanismVerdict:
    sites = graph.defs.get(name, [])
    if not sites:
        return MechanismVerdict(exists=False, invoked=False, achievable=set())

    invoked = bool(graph.callers.get(name, set()) & reachable)
    achievable: set[str] = set()
    for site in sites:
        achievable |= _achievable_severities(graph, site.node)
    return MechanismVerdict(exists=True, invoked=invoked, achievable=achievable)

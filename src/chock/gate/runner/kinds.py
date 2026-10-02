"""Gate runner: the declarative gate kinds and the `KINDS` table."""

from __future__ import annotations

import fnmatch
import json
import re
import tomllib

from .actor import _honoured, _waiver_re
from .constants import _DEPENDENCY_KIND, HEAD_WAIVER_EVENTS
from .context import GateContext, GateResult
from .script import _kind_script


# >>> gate.py 06
def _kind_content_regex(ctx: GateContext, params: dict, event: str) -> GateResult:
    content_re = re.compile(params["content_pattern"])
    forbidden_path_regex = params.get("forbidden_path_regex")
    path_re = re.compile(forbidden_path_regex) if forbidden_path_regex else None
    pragma_re = _waiver_re(params, event)
    agent = event in HEAD_WAIVER_EVENTS
    scan = params.get("scan", "added_lines")
    diff_filter = params.get("diff_filter", "ACMRT")

    matches: list[str] = []
    for path in ctx.staged_paths(diff_filter):
        head_text = ctx.committed_blob(path) if agent else ""
        head = frozenset(head_text.splitlines()) if agent else None
        if path_re and path_re.search(path):
            blob = head_text if agent else ctx.staged_blob(path)
            if not (pragma_re and pragma_re.search(blob)):
                matches.append(f"{path}: forbidden path")
        lines = ctx.staged_blob(path).splitlines() if scan == "staged_blob" else ctx.added_lines(path)
        for line in lines:
            if _honoured(pragma_re, line, head):
                continue
            if content_re.search(line):
                matches.append(f"{path}: content pattern")
                break
    return GateResult(allowed=not matches, matches=matches)


def _kind_forbidden_ref(ctx: GateContext, params: dict, event: str) -> GateResult:
    protected = [str(r) for r in params.get("refs", [])]
    if event == "push":
        candidates = [(r, r.removeprefix("refs/heads/")) for r in ctx.push_refs() if r.startswith("refs/heads/")]
    else:
        branch = ctx.head_ref or ctx.current_branch()
        candidates = [(b, b) for b in [branch] if b and b != "HEAD"]
    for shown, name in candidates:
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in protected):
            return GateResult(allowed=False, matches=[shown])
    return GateResult(allowed=True)


_REQ_RE = re.compile(r"^\s*([A-Za-z0-9._-]+)")
_GOMOD_RE = re.compile(r"^\s*([A-Za-z0-9._~/-]+\.[A-Za-z0-9._~/-]+)\s+v")


def _deps_requirements(text: str) -> set[str]:
    names: set[str] = set()
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(("#", "-")):
            continue
        m = _REQ_RE.match(line)
        if m:
            names.add(m.group(1))
    return names


def _deps_pyproject(text: str) -> set[str]:
    data = tomllib.loads(text)
    names: set[str] = set()
    project = data.get("project") or {}
    specs = list(project.get("dependencies") or [])
    for extra in (project.get("optional-dependencies") or {}).values():
        specs.extend(extra or [])
    for spec in specs:
        m = _REQ_RE.match(str(spec))
        if m:
            names.add(m.group(1))
    poetry = ((data.get("tool") or {}).get("poetry") or {}).get("dependencies") or {}
    names.update(k for k in poetry if k.lower() != "python")
    return names


def _deps_package_json(text: str) -> set[str]:
    data = json.loads(text)
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        section = data.get(key)
        if isinstance(section, dict):
            names.update(section)
    return names


def _deps_go_mod(text: str) -> set[str]:
    names: set[str] = set()
    in_block = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("require ("):
            in_block = True
            continue
        if in_block and s == ")":
            in_block = False
            continue
        candidate = s[len("require ") :] if s.startswith("require ") else (s if in_block else "")
        m = _GOMOD_RE.match(candidate)
        if m:
            names.add(m.group(1))
    return names


EXTRACTORS = {
    "requirements.txt": _deps_requirements,
    "pyproject.toml": _deps_pyproject,
    "package.json": _deps_package_json,
    "go.mod": _deps_go_mod,
}


def _extract(path: str, text: str) -> set[str]:
    fn = EXTRACTORS.get(path.rsplit("/", 1)[-1])
    if fn is None or not text.strip():
        return set()
    try:
        return fn(text)
    except Exception:  # noqa: BLE001 -- untrusted, possibly-malformed manifest content; never crash the gate on it
        return set()


def _kind_dependency_allowlist(ctx: GateContext, params: dict, _event: str) -> GateResult:
    watched = set(params.get("manifests", []))
    allow: set[str] = set()
    allow_path = ctx.repo_root / params["allowlist_file"]
    if allow_path.exists():
        for line in allow_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                allow.add(s.lower())

    matches: list[str] = []
    staged = sorted(p for p in ctx.staged_paths() if p.rsplit("/", 1)[-1] in watched)
    for path in staged:
        added = _extract(path, ctx.staged_blob(path)) - _extract(path, ctx.head_blob(path))
        for name in sorted(added):
            if name.lower() not in allow:
                matches.append(f"{path}: {name}")
    return GateResult(allowed=not matches, matches=matches)


def _count(
    pattern: "re.Pattern[str]", lines: list[str], pragma: re.Pattern[str] | None, head: frozenset[str] | None = None
) -> int:
    return sum(1 for line in lines if pattern.search(line) and not _honoured(pragma, line, head))


def _kind_test_integrity(ctx: GateContext, params: dict, event: str) -> GateResult:
    """Block a change that wins green CI by weakening the tests rather than fixing the code."""
    path_re = re.compile(params["test_path_regex"])
    assertion_re = re.compile(params["assertion_pattern"])
    dummy_pattern = params.get("dummy_assertion_pattern")
    dummy_re = re.compile(dummy_pattern) if dummy_pattern else None
    pragma_re = _waiver_re(params, event)
    agent = event in HEAD_WAIVER_EVENTS

    matches: list[str] = []
    added = removed = 0
    for path in ctx.staged_paths("D"):
        if path_re.search(path):
            matches.append(f"{path}: test file deleted")
    for path in ctx.staged_paths("ACMRT"):
        if not path_re.search(path):
            continue
        added_lines = ctx.net_added_lines(path)
        head = frozenset(ctx.committed_blob(path).splitlines()) if agent else None
        if any(_honoured(pragma_re, line, head) for line in added_lines):
            continue
        added += _count(assertion_re, added_lines, pragma_re, head)
        removed += _count(assertion_re, ctx.removed_lines(path), pragma_re, head)
        if dummy_re and any(dummy_re.search(line) for line in added_lines):
            matches.append(f"{path}: vacuous assertion added")
    if removed > added:
        matches.append(f"assertions removed across tests: {removed} removed, {added} added")
    return GateResult(allowed=not matches, matches=matches)


# >>> gate.py 08
KINDS = {
    "content_regex": _kind_content_regex,
    "forbidden_ref": _kind_forbidden_ref,
    _DEPENDENCY_KIND: _kind_dependency_allowlist,
    "test_integrity": _kind_test_integrity,
    "script": _kind_script,
}

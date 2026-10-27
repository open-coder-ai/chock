"""Gate runner: the declarative gate kinds and the `KINDS` table."""

from __future__ import annotations

import fnmatch
import json
import re
import tomllib
from collections.abc import Callable

from ..budget import PATTERN_SECONDS, close_judge, judge_patterns, pattern_judge
from .actor import _waiver_pattern
from .constants import _DEPENDENCY_KIND, HEAD_WAIVER_EVENTS
from .context import GateContext, GateResult
from .script import _kind_script


# >>> gate.py 06
class PatternDeadlineError(Exception):
    """A gate's patterns reached no verdict: the judge ran past its deadline or died, as the message says."""


def _hits(judge: dict, jobs: list[tuple[str | None, list[str]]]) -> list[set[int]]:
    """Per job of (pattern, texts), the indices of the texts the pattern matches; no pattern matches nothing."""
    found, why = judge_patterns(judge, [(pattern, texts) for pattern, texts in jobs if pattern], PATTERN_SECONDS)
    if why:
        raise PatternDeadlineError(why)
    results = iter(found)
    return [set(next(results)) if pattern else set() for pattern, _ in jobs]


def _lines(paths: list[str], read: Callable[[str], list[str]]) -> tuple[dict[str, range], list[str]]:
    """Every path's lines as `read` gives them, in one list, with each path's span of it."""
    spans: dict[str, range] = {}
    texts: list[str] = []
    for path in paths:
        found = read(path)
        spans[path] = range(len(texts), len(texts) + len(found))
        texts += found
    return spans, texts


def _waived(index: int, line: str, waivers: set[int], head: frozenset[str] | None) -> bool:
    """A waiver on `line` counts unless `head` is given and the line is not already committed."""
    return index in waivers and (head is None or line in head)


def _path_pattern(params: dict, ctx: GateContext) -> str | None:
    """The gate's forbidden-path regex, matching without case where the filesystem ignores it."""
    pattern = params.get("forbidden_path_regex")
    return f"(?i){pattern}" if pattern and ctx.case_blind else pattern


def _kind_content_regex(ctx: GateContext, params: dict, event: str) -> GateResult:
    pragma = _waiver_pattern(params, event)
    agent = event in HEAD_WAIVER_EVENTS
    whole = params.get("scan", "added_lines") == "staged_blob"
    paths = ctx.staged_paths(params.get("diff_filter", "ACMRT"))
    judge = pattern_judge()
    try:
        forbidden = sorted(_hits(judge, [(_path_pattern(params, ctx), paths)])[0])
        heads = {path: ctx.committed_blob(path) if agent else "" for path in paths}
        blobs = [heads[paths[index]] if agent else ctx.staged_blob(paths[index]) for index in forbidden]
        spans, texts = _lines(
            paths, lambda path: ctx.staged_blob(path).splitlines() if whole else ctx.added_lines(path)
        )
        jobs = [(pragma, blobs), (pragma, texts), (params["content_pattern"], texts)]
        blob_waivers, line_waivers, hits = _hits(judge, jobs)
    finally:
        close_judge(judge)
    matches: list[str] = []
    for index, path in enumerate(paths):
        if index in forbidden and forbidden.index(index) not in blob_waivers:
            matches.append(f"{path}: forbidden path")
        head = frozenset(heads[path].splitlines()) if agent else None
        if any(n in hits and not _waived(n, texts[n], line_waivers, head) for n in spans[path]):
            matches.append(f"{path}: content pattern")
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


def _count(span: range, hits: set[int], texts: list[str], waivers: set[int], head: frozenset[str] | None) -> int:
    return sum(1 for n in span if n in hits and not _waived(n, texts[n], waivers, head))


def _kind_test_integrity(ctx: GateContext, params: dict, event: str) -> GateResult:
    """Block a change that wins green CI by weakening the tests rather than fixing the code."""
    pragma = _waiver_pattern(params, event)
    agent = event in HEAD_WAIVER_EVENTS
    deleted, changed = ctx.staged_paths("D"), ctx.staged_paths("ACMRT")
    judge = pattern_judge()
    try:
        gone, tests = _hits(judge, [(params["test_path_regex"], deleted), (params["test_path_regex"], changed)])
        files = [changed[index] for index in sorted(tests)]
        added_spans, added = _lines(files, ctx.net_added_lines)
        removed_spans, removed = _lines(files, ctx.removed_lines)
        assertion = params["assertion_pattern"]
        jobs = [(assertion, added), (assertion, removed), (pragma, added), (pragma, removed)]
        jobs.append((params.get("dummy_assertion_pattern"), added))
        asserted_added, asserted_removed, waived_added, waived_removed, dummy = _hits(judge, jobs)
    finally:
        close_judge(judge)
    matches = [f"{deleted[index]}: test file deleted" for index in sorted(gone)]
    added_count = removed_count = 0
    for path in files:
        head = frozenset(ctx.committed_blob(path).splitlines()) if agent else None
        if any(_waived(n, added[n], waived_added, head) for n in added_spans[path]):
            continue
        added_count += _count(added_spans[path], asserted_added, added, waived_added, head)
        removed_count += _count(removed_spans[path], asserted_removed, removed, waived_removed, head)
        if any(n in dummy for n in added_spans[path]):
            matches.append(f"{path}: vacuous assertion added")
    if removed_count > added_count:
        matches.append(f"assertions removed across tests: {removed_count} removed, {added_count} added")
    return GateResult(allowed=not matches, matches=matches)


# >>> gate.py 08
KINDS = {
    "content_regex": _kind_content_regex,
    "forbidden_ref": _kind_forbidden_ref,
    _DEPENDENCY_KIND: _kind_dependency_allowlist,
    "test_integrity": _kind_test_integrity,
    "script": _kind_script,
}

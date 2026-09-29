#!/usr/bin/env python3
"""Chock vendored gate runner — SELF-CONTAINED, STDLIB ONLY."""

from __future__ import annotations

import argparse
import difflib
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_GIT = shutil.which("git") or "git"


@dataclass
class GateResult:
    allowed: bool
    message: str = ""
    matches: list[str] = field(default_factory=list)


def _is_outside(path: str) -> bool:
    """An absolute path: only a write the gate declared in `outside_repo` reaches the runner as one."""
    return path.startswith("/") or path[1:2] == ":"


class GateContext:
    """Read-only git facts. Every accessor swallows git errors and returns empty."""

    def __init__(
        self,
        repo_root: Path,
        push_stdin: str | None = None,
        base: str | None = None,
        head_ref: str | None = None,
        scope: Sequence[str] | None = None,
        own: Sequence[str] = (),
        session: Mapping[str, object] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        #: The session-log handle a script gate receives; None when the hook named no session.
        self.session = dict(session) if session else None
        self._push_stdin = push_stdin or ""
        self.base = base
        self.head_ref = head_ref
        #: The policy's applies_to.paths. Empty means every changed file is in scope.
        self.scope = tuple(scope or ())
        #: Path prefixes this gate never judges: its own policy's source and compiled folders.
        self.own = tuple(own)

    def in_scope(self, path: str) -> bool:
        """Whether this policy may judge this file at all.

        fnmatch semantics, so `*` crosses `/` and `.github/workflows/*` covers nested files.
        A gate with no scope sees every changed file, which is what every gate did before
        applies_to.paths was read.
        """
        if path.startswith(self.own):
            return False
        if _is_outside(path):
            return True
        return not self.scope or any(fnmatch.fnmatchcase(path, g) for g in self.scope)

    def _range(self) -> list[str]:
        """The git-diff scope: a commit range in CI, the staged index otherwise."""
        return [f"{self.base}...HEAD"] if self.base else ["--cached"]

    def _git(self, *args: str) -> str:
        try:
            proc = subprocess.run(  # noqa: S603 -- reading repo facts via git is this class's whole job
                [_GIT, "-c", "core.quotePath=false", *args],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, UnicodeError):
            return ""
        else:
            return proc.stdout or ""

    def rev_exists(self, ref: str) -> bool:
        """True when `ref` resolves to a commit. Used to fail CI closed on a missing base."""
        return bool(self._git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").strip())

    def staged_paths(self, diff_filter: str = "ACMRT") -> list[str]:
        out = self._git("diff", *self._range(), "--name-only", f"--diff-filter={diff_filter}")
        paths = (line.strip() for line in out.splitlines() if line.strip())
        return [path for path in paths if self.in_scope(path)]

    def added_lines(self, path: str) -> list[str]:
        out = self._git("diff", *self._range(), "-U0", "--", path)
        lines: list[str] = []
        for line in out.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                lines.append(line[1:])
        return lines

    def removed_lines(self, path: str) -> list[str]:
        """The deleted side of the diff -- what a test-weakening change takes away."""
        out = self._git("diff", *self._range(), "-U0", "--", path)
        return [line[1:] for line in out.splitlines() if line.startswith("-") and not line.startswith("---")]

    def staged_blob(self, path: str) -> str:
        """The proposed content: staged in index mode, committed at HEAD in range mode."""
        return self._git("show", f"HEAD:{path}" if self.base else f":{path}")

    def head_blob(self, path: str) -> str:
        """Content before the change, or "" when the path is new in it."""
        return self._git("show", f"{self.base or 'HEAD'}:{path}")

    def committed_blob(self, path: str) -> str:
        """The file as HEAD has it, or "" when HEAD does not."""
        return self._git("show", f"HEAD:{path}")

    def net_added_lines(self, path: str) -> list[str]:
        """The lines this change introduces; at a commit that is what `added_lines` already says."""
        return self.added_lines(path)

    def current_branch(self) -> str:
        branch = self._git("symbolic-ref", "--short", "HEAD").strip()
        if branch:
            return branch
        return self._git("rev-parse", "--abbrev-ref", "HEAD").strip()

    def push_refs(self) -> list[str]:
        refs: list[str] = []
        for line in self._push_stdin.splitlines():
            parts = line.split()
            if len(parts) >= _PUSH_LINE_MIN_PARTS:
                refs.append(parts[2])
        return refs


def _line_diff(old: str, new: str) -> tuple[list[str], list[str]]:
    """(added, removed) lines turning `old` into `new`, by sequence like a `-U0` diff."""
    old_lines, new_lines = old.splitlines(), new.splitlines()
    added: list[str] = []
    removed: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes():
        if tag != "equal":
            removed.extend(old_lines[i1:i2])
            added.extend(new_lines[j1:j2])
    return added, removed


class WriteContext(GateContext):
    """Files an agent is about to write, or has just written, shaped like a staged diff.

    The gate kinds are untouched and cannot tell the difference: only the material changes.
    `writes` is each file as it would be (pre-tool) or is (stop). The baseline it changed from
    is the file on disk before the write at pre-tool, and HEAD at the turn's end, where the
    disk already holds the writes. `added_lines` is an edit's own text when it carries one
    (`added`), else the diff against that baseline, so a whole-file write or a dirty file is
    judged on what changed and never on lines that were already there.

    It still subclasses GateContext so repo_root and the git-backed accessors a kind may
    reach for keep working -- an allowlist file still lives in the repository even when the
    content under judgement does not.
    """

    def __init__(
        self,
        repo_root: Path,
        writes: Mapping[str, str],
        scope: Sequence[str] | None = None,
        added: Mapping[str, str] | None = None,
        own: Sequence[str] = (),
        *,
        stop: bool = False,
        session: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(repo_root=repo_root, scope=scope, own=own, session=session)
        self._writes = dict(writes)
        self._added = dict(added or {})
        self._stop = stop

    def staged_paths(self, diff_filter: str = "ACMRT") -> list[str]:
        """Every write is a present file, so a filter asking only for deletions finds none."""
        if not set(diff_filter) & set("ACMRT"):
            return []
        return [path for path in self._writes if self.in_scope(path)]

    def staged_blob(self, path: str) -> str:
        return self._writes.get(path, "")

    def _diff(self, path: str) -> tuple[list[str], list[str]]:
        return _line_diff(self.head_blob(path), self._writes.get(path, ""))

    def added_lines(self, path: str) -> list[str]:
        if path in self._added:
            return self._added[path].splitlines()
        return self._diff(path)[0]

    def net_added_lines(self, path: str) -> list[str]:
        return self._diff(path)[0]

    def removed_lines(self, path: str) -> list[str]:
        return self._diff(path)[1]

    def head_blob(self, path: str) -> str:
        """The baseline: HEAD at the turn's end, else what is on disk now, which this write would replace."""
        if self._stop:
            return self.committed_blob(path)
        try:
            return (self.repo_root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""


#: Kinds whose question a write can answer. A branch name is not in a tool call, so
#: forbidden_ref has nothing to read here; saying so beats passing it empty and calling
#: that an allow.
_DEPENDENCY_KIND = "dependency_allowlist"
WRITE_PATH_KINDS = frozenset({"content_regex", "script", _DEPENDENCY_KIND, "test_integrity"})


#: Events at which a line-level waiver is honoured: the ones where a human staged the text. At
#: tool use the scanned text is a live tool argument, and at the turn's end it is a file the
#: same agent just wrote, so a pragma there is the refused party waiving itself -- the gateway
#: evaluator never read it for that reason, and the published policy message says so.
WAIVABLE_EVENTS = frozenset({"commit", "push", "ci"})

#: The event of both agent surfaces (pre-tool-use and stop), by the name policies declare.
TOOL_USE_EVENT = "tool_use"

#: Env var marking the commit as a coding agent's. No repo file or agentseam data records a vendor
#: env marker verified to reach a git hook, so this explicit opt-in is the only trigger.
AGENT_COMMIT_ENV = "CHOCK_AGENT_COMMIT"

#: The event an agent-made commit is judged at: outside WAIVABLE_EVENTS, so a waiver the commit
#: adds is not honoured. Coverage (`on: [commit]`) is still decided by the name `commit`.
AGENT_COMMIT_EVENT = "agent-commit"

#: Events where the actor may be the refused agent: a waiver counts only when HEAD already has that line.
HEAD_WAIVER_EVENTS = frozenset({AGENT_COMMIT_EVENT, TOOL_USE_EVENT})

_FALSY_ENV = frozenset({"", "0", "false", "no", "off"})

_AGENT_COMMIT_NOTE = (
    f"gate: this commit is treated as an agent's ({AGENT_COMMIT_ENV} is set), so a waiver it adds "
    "was not honoured; only waivers already in HEAD count. A person reviews and waives it, then "
    f"commits from their own shell with {AGENT_COMMIT_ENV} unset."
)


def agent_commit() -> bool:
    """True when the environment marks this commit as a coding agent's."""
    return os.environ.get(AGENT_COMMIT_ENV, "").strip().lower() not in _FALSY_ENV


def _judged_event(name: str) -> str:
    """The event a gate is judged at: an agent's commit reads `agent-commit`, not `commit`."""
    return AGENT_COMMIT_EVENT if name == "commit" and agent_commit() else name


def _waiver_re(params: dict, event: str) -> re.Pattern[str] | None:
    """The waiver regex for events that honour a waiver at all, else None."""
    pragma = params.get("allowlist_pragma") if event in WAIVABLE_EVENTS | HEAD_WAIVER_EVENTS else None
    return re.compile(pragma) if pragma else None


def _honoured(pragma_re: re.Pattern[str] | None, text: str, head: frozenset[str] | None) -> bool:
    """A waiver on `text` counts unless `head` is given and the text is not already committed."""
    return bool(pragma_re and pragma_re.search(text) and (head is None or text in head))


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


def _count(pattern: "re.Pattern[str]", lines: list[str], pragma: re.Pattern[str] | None) -> int:
    return sum(1 for line in lines if pattern.search(line) and not (pragma and pragma.search(line)))


def _kind_test_integrity(ctx: GateContext, params: dict, event: str) -> GateResult:
    """Block a change that wins green CI by weakening the tests rather than fixing the code."""
    path_re = re.compile(params["test_path_regex"])
    assertion_re = re.compile(params["assertion_pattern"])
    dummy_pattern = params.get("dummy_assertion_pattern")
    dummy_re = re.compile(dummy_pattern) if dummy_pattern else None
    pragma_re = _waiver_re(params, event) if event not in HEAD_WAIVER_EVENTS else None

    matches: list[str] = []
    added = removed = 0
    for path in ctx.staged_paths("D"):
        if path_re.search(path):
            matches.append(f"{path}: test file deleted")
    for path in ctx.staged_paths("ACMRT"):
        if not path_re.search(path):
            continue
        added_lines = ctx.net_added_lines(path)
        if pragma_re and any(pragma_re.search(line) for line in added_lines):
            continue
        added += _count(assertion_re, added_lines, pragma_re)
        removed += _count(assertion_re, ctx.removed_lines(path), pragma_re)
        if dummy_re and any(dummy_re.search(line) for line in added_lines):
            matches.append(f"{path}: vacuous assertion added")
    if removed > added:
        matches.append(f"assertions removed across tests: {removed} removed, {added} added")
    return GateResult(allowed=not matches, matches=matches)


#: A script gate's budget to answer. Past it the script has not decided, and an undecided
#: gate refuses.
_SCRIPT_TIMEOUT_SECONDS = 30

#: The exit codes a script gate speaks -- this runner's own, so a policy's script reads like
#: the runner that calls it. Anything else is not a verdict.
_SCRIPT_ALLOW, _SCRIPT_BLOCK = 0, 1

_UNDECIDED = " -- refusing rather than allowing what it never judged"


def _kind_script(ctx: GateContext, params: dict, event: str) -> GateResult:
    """Hand the material to the policy's own script and carry back its verdict.

    The script reads `{"event", "repo_root", "writes": {path: text}}` on stdin -- the staged
    blobs at commit and push, the write itself at tool use and at the turn's end -- so one
    script serves every surface the declarative kinds do, and reads them the same way. It
    answers with an exit code: 0 allows; 1 refuses, with its own words on stderr. A missing
    script, a crash or a timeout refuses too, in this runner's words: a gate that cannot
    reach a decision never reports an allow it never established.
    """
    named = str(params.get("script", ""))
    script = ctx.repo_root / named
    if not script.is_file():
        return GateResult(allowed=False, message=f"script gate: {named!r} is not installed{_UNDECIDED}")
    writes = {path: ctx.staged_blob(path) for path in ctx.staged_paths()}
    if not writes:
        return GateResult(allowed=True)
    material = {"event": event, "repo_root": str(ctx.repo_root), "writes": writes}
    payload = json.dumps({**material, "session": ctx.session} if ctx.session else material)
    try:
        proc = subprocess.run(  # noqa: S603 -- the script is the policy's own, named in its manifest
            [sys.executable, str(script)],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=ctx.repo_root,
            timeout=_SCRIPT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        budget = f"gave no verdict within {_SCRIPT_TIMEOUT_SECONDS}s"
        return GateResult(allowed=False, message=f"script gate: {script.name} {budget}{_UNDECIDED}")
    except OSError as exc:
        return GateResult(allowed=False, message=f"script gate: {script.name} could not run ({exc}){_UNDECIDED}")
    spoken = ((proc.stderr or "") + (proc.stdout or "")).strip()
    if proc.returncode == _SCRIPT_ALLOW:
        return GateResult(allowed=True)
    if proc.returncode == _SCRIPT_BLOCK:
        return GateResult(allowed=False, message=spoken or f"blocked by {script.name}")
    first = spoken.splitlines()[0] if spoken else ""
    detail = f": {first}" if first else ""
    return GateResult(allowed=False, message=f"script gate: {script.name} exited {proc.returncode}{detail}{_UNDECIDED}")


KINDS = {
    "content_regex": _kind_content_regex,
    "forbidden_ref": _kind_forbidden_ref,
    _DEPENDENCY_KIND: _kind_dependency_allowlist,
    "test_integrity": _kind_test_integrity,
    "script": _kind_script,
}


GATE_LOG_ENV = "CHOCK_GATE_LOG"
_LOG_MAX_BYTES = 1_048_576
_LOG_MATCH_CAP = 20

#: A pre-push stdin line is `<local ref> <local sha> <remote ref> <remote sha>`;
#: at least 3 whitespace-separated parts to reach the remote ref at index 2.
_PUSH_LINE_MIN_PARTS = 3

#: `<repo>/.chock/compiled/<policy>/git-hook/<script>`.resolve().parents needs at
#: least 4 entries to reach the `compiled` directory at index 2 and its parent
#: (the `.chock` root) at index 3.
_MIN_COMPILED_PATH_DEPTH = 4


def _log_outcome(gate_path: Path, event: str, spec: dict, result: GateResult) -> None:
    """Append one outcome record. Best effort: never raises, never changes the verdict."""
    try:
        if os.environ.get(GATE_LOG_ENV) == "0":
            return
        parents = gate_path.resolve().parents
        if len(parents) < _MIN_COMPILED_PATH_DEPTH or parents[2].name != "compiled":
            return
        log_dir = parents[3] / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "gate-events.jsonl"
        if log_path.exists() and log_path.stat().st_size > _LOG_MAX_BYTES:
            log_path.replace(log_dir / "gate-events.1.jsonl")
        record = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "policy_id": parents[1].name,
            "surface": parents[0].name,
            "event": event,
            "kind": spec.get("kind"),
            "verdict": "allow" if result.allowed else "block",
            "match_count": len(result.matches),
            "matches": result.matches[:_LOG_MATCH_CAP],
        }
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 -- best effort logging: never raises, never changes the verdict
        return


#: Both agent surfaces answer to the vocabulary policies already declare. A policy saying
#: `on: [commit, tool_use]` has been asking for both of these all along; nothing in a manifest
#: has to change for it to get them.
_EVENT_NAME = {"pre-commit": "commit", "pre-push": "push", "pre-tool-use": "tool_use", "stop": "tool_use"}

STOP_EVENT = "stop"

AGENT_EVENTS = ("pre-tool-use", STOP_EVENT)

#: `script_base` value naming the gate file's own directory as where `params.script` lives.
SCRIPT_BASE_GATE = "gate"

#: A gate skips only its own policy's folders, so a policy's evals (which carry the very
#: content its gate refuses) never trip it. The rest of `.chock/`, including other policies'
#: compiled output and the vendored runtimes, stays in scope: a file planted there is judged.
COMPILED_PREFIX = ".chock/compiled/"
POLICIES_PREFIX = ".agents/policies/"


def own_paths(gate_path: Path) -> tuple[str, ...]:
    """Prefixes a gate never judges: its own policy's shipped and compiled files."""
    parents = gate_path.resolve().parents
    if len(parents) < _MIN_COMPILED_PATH_DEPTH or parents[2].name != "compiled":
        return ()
    policy = parents[1].name
    return (f"{COMPILED_PREFIX}{policy}/", f"{POLICIES_PREFIX}{policy}/")


def _params(gate_path: Path, spec: dict) -> dict:
    """The gate's params, with a packaged script gate's program located beside the gate file."""
    params = dict(spec.get("params", {}))
    if spec.get("script_base") == SCRIPT_BASE_GATE:
        params["script"] = str(gate_path.resolve().parent / str(params.get("script", "")))
    return params


def _context(
    event: str,
    spec: dict,
    repo_root: Path,
    push_stdin: str | None,
    base: str | None,
    head_ref: str | None,
    writes: Mapping[str, str] | None,
    added: Mapping[str, str] | None = None,
    own: Sequence[str] = (),
    session: Mapping[str, object] | None = None,
) -> GateContext | None:
    """The material this event puts under judgement, or None when the kind cannot read it."""
    if event not in AGENT_EVENTS:
        return GateContext(
            repo_root=repo_root, push_stdin=push_stdin, base=base, head_ref=head_ref, scope=spec.get("paths"), own=own
        )
    if spec.get("kind") not in WRITE_PATH_KINDS:
        print(
            f"gate: kind {spec.get('kind')!r} has nothing to read at {event} -- it asks about the "
            "repository, not about a file being written. Refusing rather than reporting an allow "
            "it never established.",
            file=sys.stderr,
        )
        return None
    return WriteContext(
        repo_root=repo_root,
        writes=writes or {},
        scope=spec.get("paths"),
        added=added,
        own=own,
        stop=event == STOP_EVENT,
        session=session,
    )


def _report_refusal(result: GateResult, spec: dict, judged: str) -> None:
    print(result.message or spec.get("message", ""), file=sys.stderr)
    for m in result.matches:
        print(f"  - {m}", file=sys.stderr)
    if judged == AGENT_COMMIT_EVENT:
        print(_AGENT_COMMIT_NOTE, file=sys.stderr)


def run(
    gate_path: Path,
    event: str,
    push_stdin: str | None,
    repo_root: Path,
    base: str | None = None,
    head_ref: str | None = None,
    writes: Mapping[str, str] | None = None,
    added: Mapping[str, str] | None = None,
    session: Mapping[str, object] | None = None,
) -> int:
    gate_path = Path(gate_path)
    if not gate_path.exists():
        print(
            "gate: the compiled gate this hook names is missing, so the install is incomplete. "
            "Run `chock sync --repo .` to rebuild the compiled gates.",
            file=sys.stderr,
        )
        return 2
    try:
        spec = json.loads(gate_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"gate: cannot read {gate_path}: {exc}", file=sys.stderr)
        return 2
    if event == "ci":
        name, covered = "ci", "commit" in spec.get("on", [])
    else:
        name = _EVENT_NAME.get(event, event)
        covered = name in spec.get("on", [])
    if not covered:
        return 0
    kind = KINDS.get(spec.get("kind"))
    if kind is None:
        print(f"gate: unknown kind {spec.get('kind')!r}", file=sys.stderr)
        return 2
    ctx = _context(event, spec, repo_root, push_stdin, base, head_ref, writes, added, own_paths(gate_path), session)
    if ctx is None:
        return 2
    if event == "ci" and base and not ctx.rev_exists(base):
        print(
            f"gate: base ref {base!r} does not resolve -- refusing to scan an empty range. "
            "Fetch it (e.g. actions/checkout with fetch-depth: 0) or pass a base that exists.",
            file=sys.stderr,
        )
        return 2
    judged = _judged_event(name)
    result = kind(ctx, _params(gate_path, spec), judged)
    _log_outcome(gate_path, judged, spec, result)
    if not result.allowed:
        _report_refusal(result, spec, judged)
        return 1
    return 0


def _repo_root() -> Path:
    try:
        out = subprocess.check_output(  # noqa: S603 -- finding the repo root via git is this fallback's job
            [_GIT, "rev-parse", "--show-toplevel"], text=True, encoding="utf-8", errors="replace"
        )
        return Path(out.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, UnicodeError):
        return Path.cwd()


def _texts(raw: str, key: str) -> dict[str, str]:
    """One {path: text} map off the stdin payload. Unreadable input yields none, never a guess."""
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    texts = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(texts, dict):
        return {}
    return {str(path): str(text) for path, text in texts.items() if isinstance(text, str)}


def _session(raw: str) -> dict | None:
    """The session-log handle the hook handler put on stdin, if any."""
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return None
    session = payload.get("session") if isinstance(payload, dict) else None
    return session if isinstance(session, dict) else None


def _writes(raw: str) -> dict[str, str]:
    """The files this event puts under judgement, whole."""
    return _texts(raw, "writes")


def _utf8_streams() -> None:
    """Speak UTF-8 on stdin and stderr whatever the console code page, so a match cannot crash the verdict."""
    for stream in (sys.stdin, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _utf8_streams()
    parser = argparse.ArgumentParser(prog="gate.py")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="Run a compiled gate")
    run_p.add_argument("--gate", required=True, help="Path to compiled gate.json")
    run_p.add_argument("--event", required=True, choices=["pre-commit", "pre-push", "ci", *AGENT_EVENTS])
    run_p.add_argument("--base", help="Base ref to diff HEAD against (required for --event ci)")
    run_p.add_argument("--head-ref", help="Branch under test, e.g. $GITHUB_HEAD_REF (used by forbidden_ref)")
    args = parser.parse_args(argv)

    if args.event == "ci" and not args.base:
        parser.error("--event ci requires --base")

    if args.event in AGENT_EVENTS:
        # The files are on stdin because a tool call's content is not in the repository yet and
        # cannot be read back from it. {"writes": {"<path>": "<text>"}, "added": {"<path>": "<text>"}},
        # `added` present only for an edit, carrying the text it introduces.
        raw = sys.stdin.read()
        return run(
            Path(args.gate),
            args.event,
            None,
            _repo_root(),
            writes=_writes(raw),
            added=_texts(raw, "added"),
            session=_session(raw),
        )

    push_stdin = sys.stdin.read() if args.event == "pre-push" and not sys.stdin.isatty() else None
    return run(Path(args.gate), args.event, push_stdin, _repo_root(), base=args.base, head_ref=args.head_ref)


if __name__ == "__main__":
    raise SystemExit(main())

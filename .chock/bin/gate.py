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
import time
import tomllib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: One hook invocation's time budget, in seconds (chock.gate.budget).
ENGINE_BUDGET_SECONDS = 30


_GIT = shutil.which("git") or "git"


@dataclass
class GateResult:
    allowed: bool
    message: str = ""
    matches: list[str] = field(default_factory=list)
    #: What a script gate itself chose (`ask` or `warn`) when it did not simply refuse; the
    #: gate's declared action still caps it. Empty means "whatever the gate declares".
    verdict: str = ""
    #: Counts a gate log record carries beside the verdict (a script gate's new and baseline findings).
    detail: dict[str, int] = field(default_factory=dict)
    #: Rule id (a script finding's optional `rule`) -> how many new findings carried it.
    rules: dict[str, int] = field(default_factory=dict)
    #: The new findings themselves (a script gate's), for the GitHub annotations; never read for a verdict.
    findings: list[dict] = field(default_factory=list)


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
        except (subprocess.CalledProcessError, OSError, UnicodeError):
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

    def committed_blob(self, path: str) -> str:
        """HEAD's file, named from `repo_root` (`./`), which may sit below the git top-level."""
        return self._git("show", f"HEAD:./{path}")

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

#: Env var a person or agent sets to say who is committing: truthy marks an agent, and a value in
#: `_HUMAN_ENV` marks a person and wins over every detected marker.
AGENT_COMMIT_ENV = "CHOCK_AGENT_COMMIT"

#: Markers Claude Code's Bash tool sets in every command it runs (witnessed; a git hook inherits
#: the environment of the git process). `AI_AGENT` is `claude-code_<version>_agent` there.
CLAUDECODE_ENV = "CLAUDECODE"
AI_AGENT_ENV = "AI_AGENT"

#: Top-level key of `.chock/config.yaml` naming further variables whose presence marks an agent.
CONFIG_AGENT_ENV_KEY = "agent_commit_env"
_CONFIG_PATH = (".chock", "config.yaml")
_CONFIG_KEY_RE = re.compile(rf"^{CONFIG_AGENT_ENV_KEY}:[ \t]*(?P<rest>[^#\n]*)")
_CONFIG_ITEM_RE = re.compile(r"^[ \t]+-[ \t]*(?P<name>[^\s#]+)")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: Env var naming, comma separated, the policies whose `ask` a person has answered "go ahead".
ALLOW_ENV = "CHOCK_ALLOW"

#: The event an agent-made commit is judged at: outside WAIVABLE_EVENTS, so a waiver the commit
#: adds is not honoured. Coverage (`on: [commit]`) is still decided by the name `commit`.
AGENT_COMMIT_EVENT = "agent-commit"

#: Events where the actor may be the refused agent: a waiver counts only when HEAD already has that line.
HEAD_WAIVER_EVENTS = frozenset({AGENT_COMMIT_EVENT, TOOL_USE_EVENT})

_HUMAN_ENV = frozenset({"0", "false", "no", "off"})

_OBSERVE_NOTE = (
    "gate: {policy} found a violation that enforce would have stopped ({held}); "
    "this repo's rollout level lets it through and records it in .chock/log/gate-events.jsonl."
)

_AGENT_COMMIT_NOTE = (
    "gate: this commit is treated as an agent's ({signal}), so a waiver it adds "
    "was not honoured; only waivers already in HEAD count. A person reviews and waives it, then "
    f"commits from their own shell with {AGENT_COMMIT_ENV}=0."
)


def _config_agent_env(repo_root: Path) -> list[str]:
    """Names under `agent_commit_env:` in `.chock/config.yaml`, read without a YAML parser.

    Only an inline list (`[A, B]`), one scalar, or a block list of `- NAME` lines is read; the
    runner is stdlib-only, and anything else yields no names rather than a guess.
    """
    try:
        lines = repo_root.joinpath(*_CONFIG_PATH).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    raw: list[str] = []
    block = False
    for line in lines:
        if block:
            item = _CONFIG_ITEM_RE.match(line)
            if item:
                raw.append(item.group("name"))
                continue
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            block = False
        key = _CONFIG_KEY_RE.match(line)
        if key:
            rest = key.group("rest").strip()
            block = not rest
            raw.extend(part for part in rest.strip("[]").split(",") if part.strip())
    names = (name.strip().strip("'\"") for name in raw)
    return [name for name in names if _ENV_NAME_RE.match(name)]


def agent_signal(repo_root: Path | None = None) -> str | None:
    """The marker that makes this an agent's commit, or None for a person's.

    An explicit `CHOCK_AGENT_COMMIT` decides: truthy is an agent, `0|false|no|off` is a person
    whatever else is set (an escape hatch for a person's own git in an agent's terminal, which an
    agent can set too). Otherwise `CLAUDECODE=1`, a non-empty `AI_AGENT`, or any non-empty variable
    named in the repository's `agent_commit_env` marks an agent.
    """
    env = os.environ
    explicit = env.get(AGENT_COMMIT_ENV, "").strip().lower()
    if explicit in _HUMAN_ENV:
        return None
    if explicit:
        return AGENT_COMMIT_ENV
    if env.get(CLAUDECODE_ENV) == "1":
        return f"{CLAUDECODE_ENV}=1"
    if env.get(AI_AGENT_ENV, "").strip():
        return AI_AGENT_ENV
    configured = _config_agent_env(repo_root) if repo_root is not None else []
    return next((name for name in configured if env.get(name)), None)


def agent_commit(repo_root: Path | None = None) -> bool:
    """True when the environment marks this commit as a coding agent's."""
    return agent_signal(repo_root) is not None


#: How far a gate may escalate in this repo: `rollout:` in `.chock/config.yaml`, else enforce.
ROLLOUT_ENV = "CHOCK_ROLLOUT"
ROLLOUT_OBSERVE, ROLLOUT_ASK, ROLLOUT_ENFORCE = "observe", "ask", "enforce"
ROLLOUT_RANK = {ROLLOUT_OBSERVE: 0, ROLLOUT_ASK: 1, ROLLOUT_ENFORCE: 2}
_CONFIG_ROLLOUT_RE = re.compile(r"^rollout:[ \t]*(?P<rest>[^#\n]*)")


def rollout_level(raw: object) -> str:
    """The level `raw` names; anything absent, unreadable or unknown is enforce, never a looser guess."""
    value = raw.strip().strip("'\"") if isinstance(raw, str) else None
    return value if value in ROLLOUT_RANK else ROLLOUT_ENFORCE


def rollout_from_text(text: str) -> str:
    """The level a config's text names, read line by line and never by a YAML parser, so every reader
    (the runtime, `chock status`, the baseline check) agrees: one top-level `rollout:` line, else enforce."""
    found = [m.group("rest") for m in map(_CONFIG_ROLLOUT_RE.match, text.splitlines()) if m]
    return rollout_level(found[0]) if len(found) == 1 else ROLLOUT_ENFORCE


def _config_rollout(repo_root: Path) -> str:
    """`rollout:` in the working tree's `.chock/config.yaml`; a symlink, or an unreadable file, is enforce."""
    path = repo_root.joinpath(*_CONFIG_PATH)
    try:
        if path.is_symlink():
            return ROLLOUT_ENFORCE
        return rollout_from_text(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return ROLLOUT_ENFORCE


def committed_rollout(repo_root: Path, ref: str) -> str:
    """`rollout:` as committed at `ref`; a ref or file git cannot show is enforce."""
    try:
        shown = subprocess.run(  # noqa: S603 -- reading one committed file
            ["git", "-C", str(repo_root), "show", f"{ref}:{'/'.join(_CONFIG_PATH)}"],  # noqa: S607
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return ROLLOUT_ENFORCE
    return rollout_from_text(shown.stdout) if shown.returncode == 0 else ROLLOUT_ENFORCE


def _stricter(*levels: str) -> str:
    return max(levels, key=ROLLOUT_RANK.__getitem__)


def rollout(repo_root: Path, event: str, signal: str | None, base: str | None = None) -> str:
    """The level in force. Nothing the actor being judged can edit may lower it:

    - at ci, the base's committed level caps the head's, so a pull request cannot lower its own gates;
    - an agent (a tool call, the turn's end, an agent's commit) is held to HEAD's committed level too,
      so an uncommitted edit to the config never lowers an agent's gates;
    - `CHOCK_ROLLOUT` counts only for a person's own commit or push.
    """
    level = _config_rollout(repo_root)
    if event == "ci":
        return _stricter(level, committed_rollout(repo_root, base)) if base else ROLLOUT_ENFORCE
    if signal is not None or event not in _GIT_EVENTS:
        return _stricter(level, committed_rollout(repo_root, "HEAD"))
    override = os.environ.get(ROLLOUT_ENV, "").strip()
    return override if override in ROLLOUT_RANK else level


def _judged_event(name: str, *, agent: bool) -> str:
    """The event a gate is judged at: an agent's commit reads `agent-commit`, not `commit`."""
    return AGENT_COMMIT_EVENT if name == "commit" and agent else name


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


#: A script gate's budget to answer. Past it the script has not decided, and an undecided
#: gate refuses.
_SCRIPT_TIMEOUT_SECONDS = ENGINE_BUDGET_SECONDS

#: The exit codes a script gate speaks, the command-guard contract's: 0 allows, 1 blocks, 3 asks,
#: 4 warns. Anything else is not a verdict. The gate's declared action caps what a script may choose.
_SCRIPT_ALLOW, _SCRIPT_BLOCK, _SCRIPT_ASK, _SCRIPT_WARN = 0, 1, 3, 4

#: Interpreter-crash signatures, lower-cased: exit 1 with one of these, or with no words at all,
#: is a script that failed, not one that refused.
_CRASH_MARKERS = ("traceback (most recent call last)", "syntax error", "syntaxerror", "unexpected eof")

_UNDECIDED = " -- refusing rather than allowing what it never judged"

_FINDINGS_KEY = "findings"


def _spawn(script: Path, ctx: GateContext, payload: dict, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- the script is the policy's own, named in its manifest
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ctx.repo_root,
        timeout=timeout,
        check=False,
    )


def _is_finding(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    line = item.get("line")
    return (
        isinstance(item.get("key"), str)
        and isinstance(item.get("path"), str)
        and isinstance(line, int)
        and not isinstance(line, bool)
        and isinstance(item.get("message"), str)
        and isinstance(item.get("new", False), bool)
    )


def _findings_document(stdout: str) -> list[dict] | None:
    """The findings a script printed as its one JSON object, or None when stdout is not that document."""
    try:
        document = json.loads(stdout)
    except ValueError:
        return None
    found = document.get(_FINDINGS_KEY) if isinstance(document, dict) else None
    if not isinstance(found, list) or not all(_is_finding(item) for item in found):
        return None
    return found


#: A finding's optional `rule`: a short label, so a code fragment never reaches the log through it.
_RULE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._:/-]{0,63}")


def _rule_ids(findings: list[dict]) -> dict[str, int]:
    """Findings per declared rule id; a finding with no valid `rule` is not counted."""
    declared = (item.get("rule") for item in findings)
    return dict(Counter(rule for rule in declared if isinstance(rule, str) and _RULE_ID_RE.fullmatch(rule)))


def _new_findings(found: list[dict], baseline: list[dict]) -> list[dict]:
    """The findings the baseline does not account for: per path and key, each baseline copy absolves one."""
    unspent = Counter((item["path"], item["key"]) for item in baseline)
    fresh: list[dict] = []
    for item in found:
        slot = (item["path"], item["key"])
        if item.get("new") or not unspent[slot]:
            fresh.append(item)
        else:
            unspent[slot] -= 1
    return fresh


def _baseline_findings(ctx: GateContext, script: Path, material: dict, started: float) -> list[dict]:
    """What the script finds in the baseline text of the change's files; empty when it cannot say.

    A new file has no baseline and is left out. A run that fails, times out, prints no findings
    document, or has no budget left contributes nothing, which errs toward blocking.
    """
    texts = {path: text for path in material["writes"] if (text := ctx.head_blob(path))}
    remaining = _SCRIPT_TIMEOUT_SECONDS - (time.monotonic() - started)
    if not texts or remaining <= 0:
        return []
    try:
        proc = _spawn(script, ctx, {**material, "writes": texts, "baseline": True}, remaining)
    except (subprocess.TimeoutExpired, OSError):
        return []
    return _findings_document(proc.stdout or "") or []


def _exit_verdict(script: Path, proc: subprocess.CompletedProcess[str]) -> GateResult:
    """The verdict of a script's exit code alone, with its own words as the reason."""
    spoken = ((proc.stderr or "") + (proc.stdout or "")).strip()
    if proc.returncode == _SCRIPT_ALLOW:
        return GateResult(allowed=True)
    if proc.returncode == _SCRIPT_BLOCK:
        if not spoken or any(marker in spoken.lower() for marker in _CRASH_MARKERS):
            first = spoken.splitlines()[0] if spoken else "no reason given"
            return GateResult(allowed=False, message=f"script gate: {script.name} crashed ({first}){_UNDECIDED}")
        return GateResult(allowed=False, message=spoken)
    if proc.returncode in (_SCRIPT_ASK, _SCRIPT_WARN):
        word = "ask" if proc.returncode == _SCRIPT_ASK else "warn"
        return GateResult(allowed=False, message=spoken or f"{script.name} chose to {word}", verdict=word)
    first = spoken.splitlines()[0] if spoken else ""
    detail = f": {first}" if first else ""
    return GateResult(allowed=False, message=f"script gate: {script.name} exited {proc.returncode}{detail}{_UNDECIDED}")


def _judge_findings(
    ctx: GateContext, script: Path, material: dict, proc: subprocess.CompletedProcess[str], started: float
) -> GateResult:
    """Judge only the findings the change introduces; the change-run's exit code is the verdict for them."""
    if proc.returncode not in (_SCRIPT_ALLOW, _SCRIPT_BLOCK, _SCRIPT_ASK, _SCRIPT_WARN):
        # A document followed by a crash or an unknown exit is undecided, never a clean pass.
        return _exit_verdict(script, proc)
    found = _findings_document(proc.stdout or "") or []
    if not found:
        return GateResult(allowed=True, detail={"new_findings": 0, "baseline_findings": 0})
    baseline = _baseline_findings(ctx, script, material, started)
    fresh = _new_findings(found, baseline)
    counts = {"new_findings": len(fresh), "baseline_findings": len(baseline)}
    if not fresh or proc.returncode == _SCRIPT_ALLOW:
        return GateResult(allowed=True, detail=counts)
    lines = [f"{item['path']}:{item['line']}: {item['message']}" for item in fresh]
    verdict = {_SCRIPT_ASK: "ask", _SCRIPT_WARN: "warn"}.get(proc.returncode, "")
    return GateResult(
        allowed=False, matches=lines, verdict=verdict, detail=counts, rules=_rule_ids(fresh), findings=fresh
    )


def _kind_script(ctx: GateContext, params: dict, event: str) -> GateResult:
    """Hand the material to the policy's own script and carry back its verdict.

    The script reads `{"event", "repo_root", "writes": {path: text}}` on stdin -- the staged
    blobs at commit and push, the write itself at tool use and at the turn's end -- so one
    script serves every surface the declarative kinds do, and reads them the same way. It
    answers with an exit code: 0 allows; 1 refuses, 3 asks, 4 warns, with its own words on stderr.
    A missing script, a crash or a timeout is undecided, and an undecided gate takes its declared
    action, in this runner's words: a gate that cannot reach a decision never reports an allow it
    never established.

    A script that also prints a findings document (`{"findings": [...]}`) is run once more on
    the baseline text, and only the findings the change adds are judged (see spec/gate-dsl.md).
    """
    named = str(params.get("script", ""))
    script = ctx.repo_root / named
    if not script.is_file():
        return GateResult(allowed=False, message=f"script gate: {named!r} is not installed{_UNDECIDED}")
    writes = {path: ctx.staged_blob(path) for path in ctx.staged_paths()}
    if not writes:
        return GateResult(allowed=True)
    material = {"event": event, "repo_root": str(ctx.repo_root), "writes": writes}
    if ctx.session:
        material["session"] = ctx.session
    started = time.monotonic()
    try:
        proc = _spawn(script, ctx, material, _SCRIPT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        budget = f"gave no verdict within {_SCRIPT_TIMEOUT_SECONDS}s"
        return GateResult(allowed=False, message=f"script gate: {script.name} {budget}{_UNDECIDED}")
    except OSError as exc:
        return GateResult(allowed=False, message=f"script gate: {script.name} could not run ({exc}){_UNDECIDED}")
    if _findings_document(proc.stdout or "") is None:
        return _exit_verdict(script, proc)
    return _judge_findings(ctx, script, material, proc, started)


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


def _write_log(chock_root: Path, record: dict) -> None:
    """Append one record to `<chock_root>/log/gate-events.jsonl`, rotating past the size cap."""
    log_dir = chock_root / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "gate-events.jsonl"
    if log_path.exists() and log_path.stat().st_size > _LOG_MAX_BYTES:
        log_path.replace(log_dir / "gate-events.1.jsonl")
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps({"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **record}, ensure_ascii=False)
            + "\n"
        )


def _log_outcome(
    gate_path: Path,
    event: str,
    spec: dict,
    result: GateResult,
    verdict: str,
    extra: Mapping[str, object] | None = None,
) -> None:
    """Append one outcome record. Best effort: never raises, never changes the verdict."""
    try:
        if os.environ.get(GATE_LOG_ENV) == "0" and not _held(extra):
            return
        parents = gate_path.resolve().parents
        if len(parents) < _MIN_COMPILED_PATH_DEPTH or parents[2].name != "compiled":
            return
        record = {
            "policy_id": parents[1].name,
            "surface": parents[0].name,
            "event": event,
            "kind": spec.get("kind"),
            "verdict": verdict,
            "match_count": len(result.matches),
            "matches": result.matches[:_LOG_MATCH_CAP],
            **result.detail,
        }
        if result.rules:
            record["rules"] = result.rules
        record.update(extra or {})
        _write_log(parents[3], record)
    except Exception:  # noqa: BLE001 -- best effort logging: never raises, never changes the verdict
        return


#: Both agent surfaces answer to the vocabulary policies already declare. A policy saying
#: `on: [commit, tool_use]` has been asking for both of these all along; nothing in a manifest
#: has to change for it to get them.
_EVENT_NAME = {
    "pre-commit": "commit",
    "commit-msg": "commit",
    "pre-push": "push",
    "pre-tool-use": "tool_use",
    "stop": "tool_use",
}

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


#: What a gate does with a violation. The declared action is the ceiling: a script may choose a
#: gentler verdict at run time, never a harsher one.
ACTION_BLOCK, ACTION_ASK, ACTION_WARN = "block", "ask", "warn"
_ACTION_RANK = {ACTION_WARN: 0, ACTION_ASK: 1, ACTION_BLOCK: 2}
_ROLLOUT_CEILING = {ROLLOUT_OBSERVE: ACTION_WARN, ROLLOUT_ASK: ACTION_ASK, ROLLOUT_ENFORCE: ACTION_BLOCK}

#: Exit codes an agent-event run reports beyond 0 (allow), 1 (block) and 2 (cannot judge): the
#: command-guard contract's own, so the vendored runtimes read a gate as they read a guard.
EXIT_ASK, EXIT_WARN = 3, 4

#: The verdict of a run that could not judge, beside the actions a gate can take.
VERDICT_ERROR = "error"

_GIT_EVENTS = ("pre-commit", "pre-push", "commit-msg")


def _policy_id(gate_path: Path) -> str | None:
    """The policy a compiled gate belongs to, from `.chock/compiled/<id>/<surface>/`, else None."""
    parents = gate_path.resolve().parents
    if len(parents) < _MIN_COMPILED_PATH_DEPTH or parents[2].name != "compiled":
        return None
    return parents[1].name


def _verdict(result: GateResult, declared: str, level: str = ROLLOUT_ENFORCE) -> str:
    """`allow`, or the action this violation takes: what the kind chose, capped by the declared action and the rollout."""
    if result.allowed:
        return "allow"
    chosen = result.verdict or declared
    return min(chosen, declared, _ROLLOUT_CEILING[level], key=_ACTION_RANK.__getitem__)


#: One sentence that tells the reader to write a `chock: allow` waiver: an agent's waiver is never honoured.
_WAIVER_SENTENCE_RE = re.compile(r"(?:(?<=\.\s)|^)(?:(?!\.\s)[^\n])*?chock: allow(?:(?!\.\s)[^\n])*\.?", re.MULTILINE)
_AGENT_WAIVER_HINT = "If this must stay, ask a person to review it; an agent cannot add the waiver."
_CUSTOMISE_POINTER = (
    "A person customises this policy's rules in .agents/policies/{policy}/manifest.yaml; an agent cannot loosen them."
)


def _for_agent(text: str) -> str:
    """The text with any waiver instruction replaced by the agent's way forward."""
    return _WAIVER_SENTENCE_RE.sub(_AGENT_WAIVER_HINT, text)


def _summary(result: GateResult, policy_id: str | None) -> str:
    """One line saying how many new findings the gate refused on."""
    return (
        f"{policy_id or 'gate'} refused {len(result.matches)} new finding(s) (only lines this change adds are judged)."
    )


def _reason(result: GateResult, spec: dict, event: str = "commit", policy_id: str | None = None) -> str:
    """The refusal. A findings gate puts its findings first; at tool use the agent gets them alone."""
    agent = event in HEAD_WAIVER_EVENTS
    policy = result.message or spec.get("message", "")
    matches = list(result.matches)
    if agent:
        policy, matches = _for_agent(policy), [_for_agent(m) for m in matches]
    if "new_findings" not in result.detail:
        return "\n".join([policy, *(f"  - {m}" for m in matches)])
    if event == TOOL_USE_EVENT:
        return "\n".join([*matches, _CUSTOMISE_POINTER.format(policy=policy_id or "<id>")])
    return "\n".join([*matches, _summary(result, policy_id), policy])


def _report_refusal(result: GateResult, spec: dict, judged: str, signal: str | None, policy_id: str | None) -> None:
    reason = _reason(result, spec, judged, policy_id)
    print(_encodable(ci_inert(reason) if judged == "ci" else reason, sys.stderr), file=sys.stderr)
    if judged == AGENT_COMMIT_EVENT and signal:
        print(_AGENT_COMMIT_NOTE.format(signal=signal), file=sys.stderr)


def _annotation(policy_id: str | None, reason: str) -> str:
    """A GitHub Actions `::warning::` workflow command; the runner reads it from stdout."""
    title = _escape_property(f"chock {policy_id or 'gate'}")
    return f"::warning title={title}::{_escape_data(reason)}"


#: GitHub shows at most this many error and this many warning annotations per step.
_ANNOTATION_CAP = 10
_GITHUB_ACTIONS_ENV = "GITHUB_ACTIONS"
_STEP_SUMMARY_ENV = "GITHUB_STEP_SUMMARY"


def _github_actions() -> bool:
    return os.environ.get(_GITHUB_ACTIONS_ENV) == "true"


def _escape_data(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(text: str) -> str:
    return _escape_data(text).replace(":", "%3A").replace(",", "%2C")


def _cell(value: object) -> str:
    """Text that stays inside one markdown table cell or bullet, whatever a finding holds: no new row,
    no HTML, and no link, image or mention (a finding's text comes from the pull request)."""
    text = " ".join(str(value).split())
    for char in "\\|[]!@":
        text = text.replace(char, "\\" + char)
    return text.replace("`", "'").replace("<", "&lt;")


_LINE_BREAK = re.compile(r"\r\n|\r|\n")


def ci_inert(text: str) -> str:
    """`text` with no line a GitHub runner would parse as a workflow command.

    The runner reads commands from stdout and stderr alike, a line at a time (CR, LF or CRLF), after
    trimming it. A finding's path or message comes from the pull request, so at ci a line that would
    start with `::` is prefixed; every other line is printed as it was.
    """
    lines = _LINE_BREAK.split(text)
    return "\n".join(f"> {line}" if line.strip().startswith("::") else line for line in lines)


def _encodable(text: str, stream: Any) -> str:
    """`text` as `stream` can write it: a lone surrogate or a character its encoding lacks becomes `?`."""
    encoding = getattr(stream, "encoding", None) or "utf-8"
    return text.encode(encoding, "replace").decode(encoding, "replace")


def _repo_relative(path: str, repo_root: Path) -> str:
    """The finding's path as a repo-relative, forward-slash path; empty when it is outside the repo."""
    text = path.replace("\\", "/")
    if text.startswith("/") or re.match(r"[A-Za-z]:/", text):
        try:
            text = Path(text).resolve().relative_to(repo_root.resolve()).as_posix()
        except (ValueError, OSError):
            return ""
    parts = [part for part in text.split("/") if part not in ("", ".")]
    return "" if ".." in parts else "/".join(parts)


def _workflow_command(level: str, finding: dict, policy_id: str | None, repo_root: Path) -> str:
    """One `::error` or `::warning` command for a finding; every untrusted part is escaped."""
    rule = finding.get("rule")
    title = f"chock {policy_id or 'gate'}" + (f": {rule}" if isinstance(rule, str) and rule else "")
    props = []
    if path := _repo_relative(finding["path"], repo_root):
        props.append(f"file={_escape_property(path)}")
        if finding["line"] > 0:
            props.append(f"line={finding['line']}")
    props.append(f"title={_escape_property(title)}")
    return f"::{level} {','.join(props)}::{_escape_data(finding['message'])}"


#: What names one step of one job attempt: every gate the step runs shares its annotation budget.
_STEP_KEYS = ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "GITHUB_ACTION")


def _budget_file() -> Path | None:
    """This step's annotation budget under `RUNNER_TEMP`, or None off a runner (each gate then caps alone)."""
    temp = os.environ.get("RUNNER_TEMP")
    if not temp:
        return None
    key = "-".join(re.sub(r"[^A-Za-z0-9_.-]", "_", os.environ.get(name, "")) for name in _STEP_KEYS)
    return Path(temp) / f"chock-annotations-{key}.json"


def _take_budget(level: str, wanted: int) -> int:
    """How many of `wanted` annotations of `level` this gate may print, and record them as spent.

    A budget that cannot be read or written prints none: the step summary still lists every finding.
    """
    path = _budget_file()
    if path is None:
        return min(wanted, _ANNOTATION_CAP)
    try:
        spent = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        used = spent.get(level, 0) if isinstance(spent, dict) else _ANNOTATION_CAP
        used = used if isinstance(used, int) and not isinstance(used, bool) and used >= 0 else _ANNOTATION_CAP
        take = max(0, min(wanted, _ANNOTATION_CAP - used))
        path.write_text(json.dumps({**spent, level: used + take}), encoding="utf-8")
    except (OSError, ValueError):
        return 0
    return take


def _annotation_plan(findings: list[dict], level: str) -> tuple[list[dict], list[dict]]:
    """The findings to annotate within this step's budget and those left out, ordered by path then line."""
    ordered = sorted(findings, key=lambda item: (item["path"], item["line"], item["key"]))
    take = _take_budget(level, len(ordered)) if ordered else 0
    return ordered[:take], ordered[take:]


def _step_summary(result: GateResult, policy_id: str | None, verdict: str, overflow: list[dict]) -> str:
    """The markdown appended to the step summary: the gate's row, then any findings past the cap."""
    counts = result.detail
    lines = [
        "### Chock gate",
        "",
        "| policy | new findings | baseline | verdict |",
        "|---|---|---|---|",
        f"| {_cell(policy_id or 'gate')} | {counts['new_findings']} | {counts['baseline_findings']} | {verdict} |",
    ]
    if overflow:
        lines += ["", f"#### Not annotated ({len(overflow)}: GitHub shows 10 errors and 10 warnings per step)", ""]
        for item in overflow:
            rule = f"[{_cell(item['rule'])}] " if isinstance(item.get("rule"), str) and item["rule"] else ""
            lines.append(f"- {_cell(item['path'])}:{item['line']}: {rule}{_cell(item['message'])}")
    return "\n".join(lines) + "\n"


def _annotate(result: GateResult, verdict: str, policy_id: str | None, repo_root: Path) -> None:
    """On GitHub Actions, print one workflow command per new finding and append the step summary.

    Output only: nothing here reads or changes a verdict or exit code.
    """
    if not _github_actions() or "new_findings" not in result.detail:
        return
    level = "error" if verdict == ACTION_BLOCK else "warning"
    shown: list[dict] = []
    overflow: list[dict] = []
    if verdict != "allow":
        shown, overflow = _annotation_plan(result.findings, level)
    for item in shown:
        print(_encodable(_workflow_command(level, item, policy_id, repo_root), sys.stdout))
    summary = os.environ.get(_STEP_SUMMARY_ENV)
    if summary:
        try:
            with open(summary, "a", encoding="utf-8", errors="replace") as handle:
                handle.write(_step_summary(result, policy_id, verdict, overflow))
        except OSError as exc:
            print(f"gate: cannot write the step summary: {exc}", file=sys.stderr)


def _annotate_safely(result: GateResult, verdict: str, policy_id: str | None, repo_root: Path) -> None:
    """`_annotate`, whose failure is reported and never reaches the verdict, the refusal or the log."""
    try:
        _annotate(result, verdict, policy_id, repo_root)
    except Exception as exc:  # noqa: BLE001 -- output only: an annotation failure never changes the verdict
        print(f"gate: GitHub annotations skipped: {type(exc).__name__}", file=sys.stderr)


def allowed_ids() -> set[str]:
    """Policy ids a person named in `CHOCK_ALLOW`, comma separated."""
    return {name.strip() for name in os.environ.get(ALLOW_ENV, "").split(",") if name.strip()}


def _ask_refusal(policy_id: str | None, signal: str | None) -> str:
    """Why a hook refuses an `ask`, and the one way through: a person's explicit override."""
    if policy_id is None:
        return f"gate: this gate asks a person, a hook cannot prompt, and it has no policy id for {ALLOW_ENV} to name."
    person = f"{ALLOW_ENV}={policy_id}"
    if signal:
        person = f"{person} {AGENT_COMMIT_ENV}=0"
        who = f" This is treated as an agent's ({signal}), and an agent cannot answer for the person."
    else:
        who = ""
    return (
        f"gate: {policy_id} asks a person to decide, and a hook cannot prompt.{who} "
        f"To go ahead, a person runs this one command from their own shell with {person} set."
    )


def _ask_answered(policy_id: str | None, signal: str | None) -> bool:
    """A person's `CHOCK_ALLOW` names this policy and no agent marker is on the command."""
    return policy_id is not None and policy_id in allowed_ids() and signal is None


def _deliver(verdict: str, result: GateResult, spec: dict, event: str, policy_id: str | None) -> int:
    """Report a `warn` or `ask` in this event's own channel and return its exit code."""
    reason = _reason(result, spec, TOOL_USE_EVENT if event in AGENT_EVENTS else event, policy_id)
    if event in AGENT_EVENTS:
        print(reason, file=sys.stderr)
        # The turn's end has nobody to ask and nothing to withhold: a Stop ask is a warning.
        return EXIT_ASK if verdict == ACTION_ASK and event != STOP_EVENT else EXIT_WARN
    if event == "ci":
        if _github_actions() and result.findings:
            print(_encodable(ci_inert(f"gate: warning: {reason}"), sys.stderr), file=sys.stderr)
        else:
            print(_encodable(_annotation(policy_id, reason), sys.stdout))
        return 0
    print(f"gate: warning: {reason}", file=sys.stderr)
    return 0


def _held(extra: Mapping[str, object] | None) -> bool:
    """A record of what the rollout level let through: the evidence for enforcing, so it is written
    even when `CHOCK_GATE_LOG=0` turns the rest of the log off."""
    return bool(extra and "would_action" in extra)


def _actor(signal: str | None) -> dict[str, object]:
    """The agent marker a log record carries, when an agent acted."""
    return {"agent": signal} if signal else {}


def _held_record(held: str, level: str) -> dict[str, object]:
    """What the log keeps of an action the rollout level lowered: the evidence for switching to enforce."""
    return {"rollout": level, "would_action": held, "would_block": held == ACTION_BLOCK}


def _log_script_hook(
    policy_id: str, event: str, verdict: str, repo_root: Path, extra: Mapping[str, object] | None = None
) -> None:
    """Record a script-backed hook's warn or ask; best effort like every gate log write."""
    try:
        if os.environ.get(GATE_LOG_ENV) == "0" and not _held(extra):
            return
        record = {"policy_id": policy_id, "surface": "git-hook", "event": _EVENT_NAME.get(event, event)}
        record.update({"kind": "script-hook", "verdict": verdict, "match_count": 0, "matches": []})
        record.update(extra or {})
        _write_log(repo_root / _CONFIG_PATH[0], record)
    except Exception:  # noqa: BLE001 -- best effort logging: never raises, never changes the verdict
        return


def script_verdict(policy_id: str, event: str, code: int, repo_root: Path) -> int:
    """The exit a script-backed git hook takes for its script's exit `code` (3 asks, 4 warns).

    The script already printed its own words. A warn is allowed; an ask is refused unless a person
    named the policy in `CHOCK_ALLOW` and no agent marker is on the command.
    """
    signal = agent_signal(repo_root)
    level = rollout(repo_root, event, signal)
    if code == EXIT_WARN:
        _log_script_hook(policy_id, event, ACTION_WARN, repo_root, _actor(signal))
        return 0
    if level == ROLLOUT_OBSERVE:
        print(_OBSERVE_NOTE.format(policy=policy_id, held=ACTION_ASK), file=sys.stderr)
        _log_script_hook(
            policy_id, event, ACTION_WARN, repo_root, {**_held_record(ACTION_ASK, level), **_actor(signal)}
        )
        return 0
    if _ask_answered(policy_id, signal):
        print(f"gate: {policy_id} asked; allowed by {ALLOW_ENV}.", file=sys.stderr)
        _log_script_hook(policy_id, event, "allow", repo_root, {"override": ALLOW_ENV, **_actor(signal)})
        return 0
    print(_ask_refusal(policy_id, signal), file=sys.stderr)
    _log_script_hook(policy_id, event, ACTION_ASK, repo_root, _actor(signal))
    return 1


@dataclass(frozen=True)
class Evaluation:
    """A gate run up to its verdict: what the kind found, and the actor and rollout level it was judged under."""

    spec: dict
    result: GateResult
    level: str
    signal: str | None
    judged: str


def evaluate(
    gate_path: Path,
    event: str,
    push_stdin: str | None,
    repo_root: Path,
    base: str | None = None,
    head_ref: str | None = None,
    writes: Mapping[str, str] | None = None,
    added: Mapping[str, str] | None = None,
    session: Mapping[str, object] | None = None,
) -> Evaluation | tuple[int, str]:
    """Run a compiled gate's kind without reporting or logging: an Evaluation, or (exit code, verdict) when it ends early."""
    gate_path = Path(gate_path)
    if not gate_path.exists():
        print(
            "gate: the compiled gate this hook names is missing, so the install is incomplete. "
            "Run `chock sync --repo .` to rebuild the compiled gates.",
            file=sys.stderr,
        )
        return 2, VERDICT_ERROR
    try:
        spec = json.loads(gate_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"gate: cannot read the compiled gate this hook names: {type(exc).__name__}", file=sys.stderr)
        return 2, VERDICT_ERROR
    if event == "ci":
        name, covered = "ci", "commit" in spec.get("on", [])
    else:
        name = _EVENT_NAME.get(event, event)
        covered = name in spec.get("on", [])
    if not covered:
        return 0, "allow"
    kind = KINDS.get(spec.get("kind"))
    if kind is None:
        print(f"gate: unknown kind {spec.get('kind')!r}", file=sys.stderr)
        return 2, VERDICT_ERROR
    declared = spec.get("action", ACTION_BLOCK)
    if declared not in _ACTION_RANK:
        print(f"gate: unknown action {declared!r} (block, ask or warn)", file=sys.stderr)
        return 2, VERDICT_ERROR
    ctx = _context(event, spec, repo_root, push_stdin, base, head_ref, writes, added, own_paths(gate_path), session)
    if ctx is None:
        return 2, VERDICT_ERROR
    if event == "ci" and base and not ctx.rev_exists(base):
        print(
            f"gate: base ref {base!r} does not resolve -- refusing to scan an empty range. "
            "Fetch it (e.g. actions/checkout with fetch-depth: 0) or pass a base that exists.",
            file=sys.stderr,
        )
        return 2, VERDICT_ERROR
    signal = agent_signal(repo_root)
    judged = _judged_event(name, agent=signal is not None)
    result = kind(ctx, _params(gate_path, spec), judged)
    return Evaluation(spec, result, rollout(repo_root, event, signal, base), signal, judged)


def judge(
    gate_path: Path,
    event: str,
    push_stdin: str | None,
    repo_root: Path,
    base: str | None = None,
    head_ref: str | None = None,
    writes: Mapping[str, str] | None = None,
    added: Mapping[str, str] | None = None,
    session: Mapping[str, object] | None = None,
) -> tuple[int, str]:
    """Run a compiled gate: (exit code, verdict), the verdict being allow, block, ask, warn or error."""
    outcome = evaluate(gate_path, event, push_stdin, repo_root, base, head_ref, writes, added, session)
    if isinstance(outcome, tuple):
        return outcome
    if event == "ci":
        declared = outcome.spec.get("action", ACTION_BLOCK)
        verdict = _verdict(outcome.result, declared, outcome.level)
        _annotate_safely(outcome.result, verdict, _policy_id(gate_path), repo_root)
    return _conclude(gate_path, outcome.spec, event, outcome.judged, outcome.result, (outcome.signal, outcome.level))


def run(gate_path: Path, event: str, push_stdin: str | None, repo_root: Path, **options: Any) -> int:
    """Run a compiled gate and return its process exit code: 0 allow, 1 block, 2 cannot judge, 3 ask, 4 warn."""
    return judge(gate_path, event, push_stdin, repo_root, **options)[0]


def _conclude(
    gate_path: Path, spec: dict, event: str, judged: str, result: GateResult, actor: tuple[str | None, str]
) -> tuple[int, str]:
    """Log the outcome and act on it: (exit code, verdict), and the words in the channel this event has.

    `actor` is the agent marker (or None) and the rollout level in force.
    """
    signal, level = actor
    declared = spec.get("action", ACTION_BLOCK)
    verdict = _verdict(result, declared, level)
    held = _verdict(result, declared)
    policy_id = _policy_id(gate_path)
    answered = verdict == ACTION_ASK and event in _GIT_EVENTS and _ask_answered(policy_id, signal)
    extra = {**(_held_record(held, level) if held != verdict else {}), **_actor(signal)}
    if answered:
        extra["override"] = ALLOW_ENV
    _log_outcome(gate_path, judged, spec, result, "allow" if answered else verdict, extra)
    if held != verdict:
        print(_OBSERVE_NOTE.format(policy=policy_id or "gate", held=held), file=sys.stderr)
    if answered:
        print(f"gate: {policy_id} asked; allowed by {ALLOW_ENV}.", file=sys.stderr)
        return 0, "allow"
    if verdict == ACTION_BLOCK:
        _report_refusal(result, spec, judged, signal, policy_id)
        return 1, verdict
    if verdict == ACTION_ASK and event in _GIT_EVENTS:
        print(_reason(result, spec, judged, policy_id), file=sys.stderr)
        print(_ask_refusal(policy_id, signal), file=sys.stderr)
        return 1, verdict
    return (0 if verdict == "allow" else _deliver(verdict, result, spec, event, policy_id)), verdict


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
    verdict_p = sub.add_parser("script-verdict", help="Settle a script-backed git hook's exit 3 (ask) or 4 (warn)")
    verdict_p.add_argument("--policy", required=True, help="Policy id the script belongs to")
    verdict_p.add_argument("--event", required=True, choices=_GIT_EVENTS)
    verdict_p.add_argument("--exit", required=True, type=int, choices=[EXIT_ASK, EXIT_WARN], dest="code")
    args = parser.parse_args(argv)

    if args.command == "script-verdict":
        return script_verdict(args.policy, args.event, args.code, _repo_root())

    if args.event == "ci" and not args.base:
        parser.error("--event ci requires --base")

    if args.event in AGENT_EVENTS:
        # The files are on stdin because a tool call's content is not in the repository yet and
        # cannot be read back from it. {"writes": {"<path>": "<text>"}, "added": {"<path>": "<text>"}},
        # `added` present only for an edit, carrying the text it introduces.
        # Paths are named from the directory the runtime works in, which may sit below the git top-level.
        raw = sys.stdin.read()
        return run(
            Path(args.gate),
            args.event,
            None,
            Path.cwd(),
            writes=_writes(raw),
            added=_texts(raw, "added"),
            session=_session(raw),
        )

    push_stdin = sys.stdin.read() if args.event == "pre-push" and not sys.stdin.isatty() else None
    return run(Path(args.gate), args.event, push_stdin, _repo_root(), base=args.base, head_ref=args.head_ref)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Chock vendored gate runner — SELF-CONTAINED, STDLIB ONLY."""

from __future__ import annotations

import argparse
import contextlib
import difflib
import fnmatch
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE_BUDGET_SECONDS = 30


BYTECODE_OFF = {"PYTHONDONTWRITEBYTECODE": "1"}


PATTERN_SECONDS = 10


PATTERN_START_SECONDS = 10


PATTERN_JUDGE_EXITED = "the pattern judge exited early ("


PATTERN_JUDGE_READY = "ready"


PATTERN_JUDGE_SOURCE = (
    "import json, re, sys\n"
    "print('ready', flush=True)\n"
    "for line in sys.stdin:\n"
    "    out = []\n"
    "    for pattern, texts in json.loads(line):\n"
    "        search = re.compile(pattern).search\n"
    "        out.append([index for index, text in enumerate(texts) if search(text)])\n"
    "    print(json.dumps(out), flush=True)\n"
)


def engine_deadline():
    """The monotonic instant this invocation's budget runs out."""
    return time.monotonic() + ENGINE_BUDGET_SECONDS


def engine_remaining(deadline):
    """Seconds left before `deadline`, never negative."""
    return max(deadline - time.monotonic(), 0.0)


def time_left(deadline, cmd):
    """Seconds left for a subprocess; raises TimeoutExpired when none are, so the caller's timeout path runs."""
    left = deadline - time.monotonic()
    if left <= 0:
        raise subprocess.TimeoutExpired(cmd, 0)
    return left


def allowed_seconds(expired):
    """The time a timed-out call was actually given, as text (what the deadline left it, not the full budget)."""
    return f"{max(float(expired.timeout or 0), 0.0):.1f}s"


def pattern_judge(interpreter=None):
    """A pattern judge, not yet started: the interpreter to run the patterns in (this one by default)."""
    return {"argv": [interpreter or sys.executable, "-I", "-c", PATTERN_JUDGE_SOURCE], "proc": None, "lines": None}


def _pump_lines(proc, lines):
    for line in proc.stdout:
        lines.put(line)
    lines.put(None)


def _start_judge(judge):
    proc = subprocess.Popen(  # noqa: S603 -- the child is this module's own source, run by this interpreter
        judge["argv"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    lines = queue.Queue()
    threading.Thread(target=_pump_lines, args=(proc, lines), daemon=True).start()
    judge["proc"], judge["lines"] = proc, lines
    try:
        ready = lines.get(timeout=PATTERN_START_SECONDS)
    except queue.Empty:
        close_judge(judge)
        return f"the pattern judge did not start within {PATTERN_START_SECONDS}s"
    if ready is None or ready.strip() != PATTERN_JUDGE_READY:
        return f"{PATTERN_JUDGE_EXITED}{close_judge(judge)})"
    return None


def close_judge(judge):
    """Stop the judge's child, if one runs; the last line it wrote to stderr, or ""."""
    proc = judge["proc"]
    judge["proc"] = judge["lines"] = None
    if proc is None:
        return ""
    if proc.poll() is None:
        proc.kill()  # before closing stdout: the reader thread holds it until the child's EOF
    proc.wait()
    try:
        spoken = proc.stderr.read()
    except (OSError, ValueError):
        spoken = ""
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        with contextlib.suppress(OSError):
            stream.close()
    return (spoken.strip().splitlines() or [""])[-1]


def _ensure_judge(judge):
    """None when the judge's child runs (started now if need be); otherwise why it could not."""
    if judge["proc"] is not None:
        return None
    try:
        return _start_judge(judge)
    except OSError as exc:
        return f"the pattern judge could not start ({exc})"


def judge_patterns(judge, jobs, seconds):
    """(hits, None) or (None, why): per job of (pattern, texts), the indices of the texts the pattern matches.

    A job that runs past `seconds` kills the child and names the time; a job with no text is never
    sent. `why` is text for a refusal: the judge is undecided and an undecided gate refuses.
    """
    if not any(texts for _, texts in jobs):
        return [[] for _ in jobs], None
    failed = _ensure_judge(judge)
    if failed:
        return None, failed
    proc, lines = judge["proc"], judge["lines"]
    try:
        proc.stdin.write(json.dumps(jobs) + "\n")
        proc.stdin.flush()
    except (OSError, ValueError):
        return None, f"{PATTERN_JUDGE_EXITED}{close_judge(judge)})"
    try:
        line = lines.get(timeout=seconds)
    except queue.Empty:
        close_judge(judge)
        return None, f"the patterns gave no verdict within {seconds:g}s (a catastrophic pattern?)"
    if line is None:
        return None, f"{PATTERN_JUDGE_EXITED}{close_judge(judge)})"
    return json.loads(line), None


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
    """Read-only git facts. A path listing raises ListingError on a git error; every other accessor returns empty."""

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

    def _listing(self, command: str, *args: str) -> list[str]:
        """A `-z` path listing; raises ListingError when git fails or its output does not parse."""
        try:
            proc = subprocess.run(  # noqa: S603 -- reading repo facts via git is this class's whole job
                [_GIT, "--literal-pathspecs", command, "-z", *args],
                cwd=str(self.repo_root),
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            msg = f"git could not run ({exc})"
            raise ListingError(msg) from exc
        if proc.returncode:
            first = (proc.stderr.decode("utf-8", "replace").strip().splitlines() or [""])[0]
            msg = f"git {command} failed (exit {proc.returncode}): {first}"
            raise ListingError(msg)
        return _nul_paths(proc.stdout)

    def _git(self, *args: str) -> str:
        try:
            proc = subprocess.run(  # noqa: S603 -- reading repo facts via git is this class's whole job
                [_GIT, "--literal-pathspecs", "-c", "core.quotePath=false", *args],
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
        paths = self._listing("diff", *self._range(), "--name-only", f"--diff-filter={diff_filter}")
        return [path for path in paths if self.in_scope(path)]

    def _diff_text(self, path: str) -> str:
        """`path`'s `-U0` diff as git writes it, unconverted; raises DiffError when git fails."""
        args = ("diff", *self._range(), "-U0", "--no-color", "--no-ext-diff", "--no-textconv", "--", path)
        try:
            proc = subprocess.run(  # noqa: S603 -- reading repo facts via git is this class's whole job
                [_GIT, "--literal-pathspecs", *args],
                cwd=str(self.repo_root),
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            msg = f"git could not run ({exc})"
            raise DiffError(msg) from exc
        if proc.returncode:
            first = (proc.stderr.decode("utf-8", "replace").strip().splitlines() or [""])[0]
            msg = f"git diff failed (exit {proc.returncode}): {first}"
            raise DiffError(msg)
        return proc.stdout.decode("utf-8", "replace")

    def added_lines(self, path: str) -> list[str]:
        return _diff_sides(self._diff_text(path))[0]

    def removed_lines(self, path: str) -> list[str]:
        """The deleted side of the diff -- what a test-weakening change takes away."""
        return _diff_sides(self._diff_text(path))[1]

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

#: Env var that says an agent is acting: truthy marks an agent. A value in `_HUMAN_ENV` unsets this
#: one variable and clears no vendor marker, since an agent can set it too.
AGENT_COMMIT_ENV = "CHOCK_AGENT_COMMIT"

#: Markers Claude Code's Bash tool sets in every command it runs (witnessed; a git hook inherits
#: the environment of the git process). `AI_AGENT` is `claude-code_<version>_agent` there.
CLAUDECODE_ENV = "CLAUDECODE"
AI_AGENT_ENV = "AI_AGENT"

#: Who acted, as a log record's `actor` names it: a person, or `agent:<client>`.
ACTOR_PERSON = "person"
ACTOR_AGENT_PREFIX = "agent:"
_ACTOR_UNSAFE = re.compile(r"[^a-z0-9_]")
_ACTOR_CLIENT_CAP = 32

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
    "commits from their own shell."
)


def _config_agent_env(repo_root: Path) -> list[str]:
    """Names under `agent_commit_env:` in `.chock/config.yaml`, in the working tree and as committed at HEAD.

    Both, so an uncommitted edit that drops a name never hides the agent it named. Read without a YAML parser:
    only an inline list (`[A, B]`), one scalar, or a block list of `- NAME` lines is read; the runner is
    stdlib-only, and anything else yields no names rather than a guess.
    """
    try:
        working = repo_root.joinpath(*_CONFIG_PATH).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        working = ""
    names = _env_names(working)
    return names + [name for name in _env_names(_committed_config(repo_root, "HEAD") or "") if name not in names]


def _env_names(text: str) -> list[str]:
    lines = text.splitlines()
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
    """The first agent marker set, or None for a person's shell: a truthy `CHOCK_AGENT_COMMIT`, `CLAUDECODE=1`,
    a non-empty `AI_AGENT`, or any non-empty variable named under the repository's `agent_commit_env`.

    One rule for every check (commit, push, tool call, stop, resume, the person-only commands). `CHOCK_AGENT_COMMIT=0`
    clears nothing a vendor set, since an agent can set it too: a person's git in an agent's terminal is told apart
    by having no vendor marker, which is what their own shell has.
    """
    env = os.environ
    named = env.get(AGENT_COMMIT_ENV, "").strip().lower()
    checks = (
        (AGENT_COMMIT_ENV, bool(named) and named not in _HUMAN_ENV),
        (f"{CLAUDECODE_ENV}=1", env.get(CLAUDECODE_ENV) == "1"),
        (AI_AGENT_ENV, bool(env.get(AI_AGENT_ENV, "").strip())),
        *((name, bool(env.get(name))) for name in (_config_agent_env(repo_root) if repo_root is not None else [])),
    )
    return next((signal for signal, present in checks if present), None)


def actor_of(signal: str | None) -> str:
    """Who acted, as a log record names it: `person`, or `agent:<client>` from the marker (`unknown` when it names none)."""
    if signal is None:
        return ACTOR_PERSON
    client = "claude_code" if signal == f"{CLAUDECODE_ENV}=1" else ""
    if signal == AI_AGENT_ENV:  # `claude-code_<version>_agent`: the client is the first word
        client = _ACTOR_UNSAFE.sub("", os.environ.get(AI_AGENT_ENV, "").split("_")[0].replace("-", "_").lower())
    return ACTOR_AGENT_PREFIX + (client[:_ACTOR_CLIENT_CAP] or "unknown")


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


def _committed_config(repo_root: Path, ref: str) -> str | None:
    """`.chock/config.yaml` as committed at `ref`; None when git cannot show it."""
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
        return None
    return shown.stdout if shown.returncode == 0 else None


def committed_rollout(repo_root: Path, ref: str) -> str:
    """`rollout:` as committed at `ref`; a ref or file git cannot show is enforce."""
    text = _committed_config(repo_root, ref)
    return ROLLOUT_ENFORCE if text is None else rollout_from_text(text)


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


def _waiver_pattern(params: dict, event: str) -> str | None:
    """The waiver pattern for events that honour a waiver at all, else None."""
    pragma = params.get("allowlist_pragma") if event in WAIVABLE_EVENTS | HEAD_WAIVER_EVENTS else None
    return str(pragma) if pragma else None


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


def _kind_content_regex(ctx: GateContext, params: dict, event: str) -> GateResult:
    pragma = _waiver_pattern(params, event)
    agent = event in HEAD_WAIVER_EVENTS
    whole = params.get("scan", "added_lines") == "staged_blob"
    paths = ctx.staged_paths(params.get("diff_filter", "ACMRT"))
    judge = pattern_judge()
    try:
        forbidden = sorted(_hits(judge, [(params.get("forbidden_path_regex"), paths)])[0])
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


#: A script gate's budget to answer. Past it the script has not decided, and an undecided
#: gate refuses.
_SCRIPT_TIMEOUT_SECONDS = ENGINE_BUDGET_SECONDS

#: The exit codes a script gate speaks, the command-guard contract's: 0 allows, 1 blocks, 3 asks,
#: 4 warns. Anything else is not a verdict. The gate's declared action caps what a script may choose.
_SCRIPT_ALLOW, _SCRIPT_BLOCK, _SCRIPT_ASK, _SCRIPT_WARN = 0, 1, 3, 4

#: Interpreter-crash signatures, lower-cased: exit 1 with one of these, or with no words at all,
#: is a script that failed, not one that refused.
_CRASH_MARKERS = ("traceback (most recent call last)", "syntax error", "syntaxerror", "unexpected eof")

#: Running a gate never writes bytecode into the pack it judges.
_BYTECODE_OFF = {"PYTHONDONTWRITEBYTECODE": "1"}

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
        env={**os.environ, **_BYTECODE_OFF},
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
#: What an agent hook's runtime hands gate.py for its decision line (the `log` stdin key), each capped.
_LOG_FIELDS = ("session_id", "actor", "target", "call")
_LOG_FIELD_CAP = 512

#: A pre-push stdin line is `<local ref> <local sha> <remote ref> <remote sha>`;
#: at least 3 whitespace-separated parts to reach the remote ref at index 2.
_PUSH_LINE_MIN_PARTS = 3

#: `<repo>/.chock/compiled/<policy>/git-hook/<script>`.resolve().parents needs at
#: least 4 entries to reach the `compiled` directory at index 2 and its parent
#: (the `.chock` root) at index 3.
_MIN_COMPILED_PATH_DEPTH = 4


def _write_log(chock_root: Path, record: dict) -> None:
    """Append one sync-route record to `<chock_root>/log/gate-events.jsonl` at the level in force."""
    log_write(chock_root / "log" / "gate-events.jsonl", {"route": "sync", **record}, chock_root.parent)


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


_UNJUDGED = " -- refusing rather than allowing what it never judged."


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
    policy, matches = _inert_lines(policy), [inert(m) for m in matches]
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
    return (
        _BREAKS_KEPT.sub(lambda run: inert(run.group()), text)
        .replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
    )


def _escape_property(text: str) -> str:
    return _escape_data(text).replace(":", "%3A").replace(",", "%2C")


def _cell(value: object) -> str:
    """Text that stays inside one markdown table cell or bullet, whatever a finding holds: no new row,
    no HTML, and no link, image or mention (a finding's text comes from the pull request)."""
    text = inert(" ".join(str(value).split()))
    for char in "\\|[]!@":
        text = text.replace(char, "\\" + char)
    return text.replace("`", "'").replace("<", "&lt;")


_LINE_BREAK = re.compile(r"\r\n|\r|\n")
#: A run of text between line breaks.
_BREAKS_KEPT = re.compile(r"[^\r\n]+")
#: Control (C0, DEL, C1), surrogate, line/paragraph separator and format (bidi, invisible) characters.
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cs", "Zl", "Zp", "Cf"})
#: Format characters that ordinary text needs: ZWNJ and ZWJ join Persian, Indic and emoji sequences.
_KEPT = frozenset({"\u200c", "\u200d"})
_NAMED = {"\t": "\\t", "\n": "\\n", "\r": "\\r"}


def _shown(char: str) -> str:
    if char in _KEPT or unicodedata.category(char) not in _UNSAFE_CATEGORIES:
        return char
    code = ord(char)
    if char in _NAMED:
        return _NAMED[char]
    return f"\\x{code:02x}" if code < 0x100 else f"\\u{code:04x}" if code < 0x10000 else f"\\U{code:08x}"  # noqa: PLR2004


def inert(value: object) -> str:
    """`value` as one line of text, each unsafe character written as a visible escape (ESC as `\\x1b`).

    The same rule as `chock.display.inert`, vendored so the runtime stays self-contained.
    """
    text = str(value)
    return text if text.isprintable() else "".join(map(_shown, text))


def _inert_lines(text: str) -> str:
    """`text` made `inert` line by line: its lines stay lines (LF), nothing else unsafe reaches the terminal."""
    return "\n".join(inert(line) for line in _LINE_BREAK.split(text))


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


def git_email(repo_root: Path | None = None) -> str:
    """The person's git `user.email`, as their shell's git reads it; empty when git names none."""
    where = ["-C", str(repo_root)] if repo_root is not None else []
    try:
        shown = subprocess.run(  # noqa: S603 -- reading one git setting
            ["git", *where, "config", "user.email"],  # noqa: S607
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return ""
    return shown.stdout.strip() if shown.returncode == 0 else ""


def approval(repo_root: Path | None = None) -> dict[str, str]:
    """What an override's record keeps of who approved it: `CHOCK_ALLOW` and the person's git email. Local log only."""
    return {"override": ALLOW_ENV, "approver": git_email(repo_root) or "unknown"}


def _ask_refusal(policy_id: str | None, signal: str | None) -> str:
    """Why a hook refuses an `ask`, and the one way through: a person's explicit override, which only a person is told."""
    if policy_id is None:
        return f"gate: this gate asks a person, a hook cannot prompt, and it has no policy id for {ALLOW_ENV} to name."
    lead = f"gate: {policy_id} asks a person to decide, and a hook cannot prompt."
    if signal:
        return (
            f"{lead} This is treated as an agent's ({signal}), and an agent cannot answer for the person: "
            "ask them. If they agree, they run this one command from their own shell."
        )
    return f"{lead} To go ahead, a person runs this one command from their own shell with {ALLOW_ENV}={policy_id} set."


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


def _actor(signal: str | None, fields: Mapping[str, object] | None = None, *, hook: bool = False) -> dict[str, object]:
    """Who acted: the agent marker, when there is one, and `actor`; plus what an agent hook's runtime gave.

    `fields` is the runtime's `log` stdin key (session_id, actor, target), kept only as short strings. An
    agent `hook` with no marker and no runtime actor is still an agent's call: `agent:unknown`, never a person.
    """
    record: dict[str, object] = {"agent": signal} if signal else {}
    record["actor"] = actor_of(signal) if signal or not hook else ACTOR_AGENT_PREFIX + "unknown"
    for key in _LOG_FIELDS:
        value = (fields or {}).get(key)
        if isinstance(value, str) and 0 < len(value) <= _LOG_FIELD_CAP:
            record[key] = value
    return record


def _held_record(held: str, level: str) -> dict[str, object]:
    """What the log keeps of an action the rollout level lowered: the evidence for switching to enforce."""
    return {"rollout": level, "would_action": held, "would_block": held == ACTION_BLOCK}


def _log_script_hook(
    policy_id: str, event: str, verdict: str, repo_root: Path, extra: Mapping[str, object] | None = None
) -> None:
    """Record a script-backed hook's warn or ask; best effort like every gate log write."""
    try:
        record = {"policy_id": policy_id, "surface": "git-hook", "event": _EVENT_NAME.get(event, event)}
        record.update({"kind": "script-hook", "verdict": verdict, "match_count": 0, "matches": []})
        record.update(extra or {})
        _write_log(repo_root / _CONFIG_PATH[0], record)
    except Exception:  # noqa: BLE001 -- best effort logging: never raises, never changes the verdict
        return


def _log_halt(repo_root: Path, record: Mapping[str, object]) -> None:
    """Record a call the repo stop refused; best effort like every gate log write."""
    try:
        _write_log(repo_root / _CONFIG_PATH[0], dict(record))
    except Exception:  # noqa: BLE001 -- best effort logging: never raises, never changes the verdict
        return


def script_verdict(policy_id: str, event: str, code: int, repo_root: Path) -> int:
    """The exit a script-backed git hook takes for its script's exit `code` (3 asks, 4 warns).

    The script already printed its own words. A warn is allowed; an ask is refused unless a person
    named the policy in `CHOCK_ALLOW` and no agent marker is on the command.
    """
    halted = halt_git(repo_root, event, policy_id)
    if halted is not None:
        return halted[0]
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
        _log_script_hook(policy_id, event, "allow", repo_root, {**approval(repo_root), **_actor(signal)})
        return 0
    print(_ask_refusal(policy_id, signal), file=sys.stderr)
    _log_script_hook(policy_id, event, ACTION_ASK, repo_root, _actor(signal))
    return 1


def halt_git(repo_root: Path, event: str, policy_id: str | None = None) -> tuple[int, str] | None:
    """An agent's commit or push while a stop reaches it: refused and logged with reason `stopped`, whatever
    `CHOCK_ALLOW`, `CHOCK_AGENT_COMMIT=0` or the rollout level say. A person's own commit or push is not the
    stop's: None."""
    signal = agent_signal(repo_root)
    who = _actor(signal)
    client = str(who["actor"]).removeprefix(ACTOR_AGENT_PREFIX)
    stop = (halt_find(halt_git_roots(repo_root), client) or halt_everywhere_read()) if signal is not None else None
    if stop is None:
        return None
    print(f"gate: {halt_message(stop)}", file=sys.stderr)
    judged = _judged_event(_EVENT_NAME.get(event, event), agent=True)
    record = {"policy_id": policy_id or HALT_POLICY, "surface": "git-hook", "event": judged, "verdict": ACTION_BLOCK}
    record.update(reason=HALT_REASON, **who)
    _log_halt(repo_root, record)
    return 1, ACTION_BLOCK


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
    result = _judge_kind(kind, ctx, _params(gate_path, spec), judged, gate_path)
    if isinstance(result, tuple):
        return result
    return Evaluation(spec, result, rollout(repo_root, event, signal, base), signal, judged)


def _judge_kind(kind: Any, ctx: Any, params: dict, judged: str, gate_path: Path) -> GateResult | tuple[int, str]:
    """The kind's result, or (2, error) with the reason on stderr when it could not judge."""
    try:
        return kind(ctx, params, judged)
    except ListingError as exc:
        print(f"gate: {inert(str(exc))} -- refusing rather than judging a change it cannot read.", file=sys.stderr)
    except PatternDeadlineError as exc:
        # The reason names a time or the judge's own last stderr line, never the judged text.
        reason = f"gate: {_policy_id(gate_path) or gate_path.name}: {inert(str(exc))}{_UNJUDGED}"
        print(reason, file=sys.stderr)
    return 2, VERDICT_ERROR


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
    fields: Mapping[str, object] | None = None,
) -> tuple[int, str]:
    """Run a compiled gate: (exit code, verdict), the verdict being allow, block, ask, warn or error.

    `fields` is what an agent hook's runtime gives the decision line: session_id, actor, target.
    """
    halted = halt_git(Path(repo_root), event, _policy_id(Path(gate_path))) if event in _GIT_EVENTS else None
    if halted is not None:
        return halted
    outcome = evaluate(gate_path, event, push_stdin, repo_root, base, head_ref, writes, added, session)
    if isinstance(outcome, tuple):
        return outcome
    if event == "ci":
        declared = outcome.spec.get("action", ACTION_BLOCK)
        verdict = _verdict(outcome.result, declared, outcome.level)
        _annotate_safely(outcome.result, verdict, _policy_id(gate_path), repo_root)
    return _conclude(
        gate_path, outcome.spec, event, outcome.judged, outcome.result, (outcome.signal, outcome.level, fields)
    )


def run(gate_path: Path, event: str, push_stdin: str | None, repo_root: Path, **options: Any) -> int:
    """Run a compiled gate and return its process exit code: 0 allow, 1 block, 2 cannot judge, 3 ask, 4 warn."""
    return judge(gate_path, event, push_stdin, repo_root, **options)[0]


def _conclude(
    gate_path: Path,
    spec: dict,
    event: str,
    judged: str,
    result: GateResult,
    actor: tuple[str | None, str, Mapping[str, object] | None],
) -> tuple[int, str]:
    """Log the outcome and act on it: (exit code, verdict), and the words in the channel this event has.

    `actor` is the agent marker (or None), the rollout level in force, and the runtime's log fields (or None).
    """
    signal, level, fields = actor
    declared = spec.get("action", ACTION_BLOCK)
    verdict = _verdict(result, declared, level)
    held = _verdict(result, declared)
    policy_id = _policy_id(gate_path)
    answered = verdict == ACTION_ASK and event in _GIT_EVENTS and _ask_answered(policy_id, signal)
    who = _actor(signal, fields, hook=event in AGENT_EVENTS)
    extra = {**(_held_record(held, level) if held != verdict else {}), **who}
    if answered:
        extra.update(approval())
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


#: The level a person set for this shell's hooks; an agent's tool input never reaches a hook's environment.
LOG_LEVEL_ENV = "CHOCK_LOG_LEVEL"
#: Deprecated: `CHOCK_GATE_LOG=0` reads as `CHOCK_LOG_LEVEL=off`.
LOG_LEGACY_ENV = "CHOCK_GATE_LOG"
LOG_OFF, LOG_INFO, LOG_DEBUG = "off", "info", "debug"
LOG_LEVELS = (LOG_OFF, LOG_INFO, LOG_DEBUG)
#: One settings file per scope: `<repo>/.chock/chock-log.json`, then `~/.chock/chock-log.json`. A person edits it.
LOG_SETTINGS_PARTS = (".chock", "chock-log.json")
LOG_SETTINGS_KEYS = ("level", "max_bytes")
LOG_DEFAULT_MAX_BYTES = 1_048_576
LOG_MIN_MAX_BYTES = 65_536
LOG_MAX_MAX_BYTES = 1_073_741_824
LOG_ALLOW = "allow"
#: Fields that make an allow a decision worth an info line: something let a policy's finding through,
#: or an agent's action, kept as its fingerprint (`target`) so the log can say what the agent touched.
LOG_LET_THROUGH = ("override", "would_action", "target")
#: A debug trace's command or path is cut to this many characters, after redaction.
LOG_TRACE_CAP = 200
LOG_REDACTED = "[redacted]"
#: The client's id for one tool call (`tool_use_id`): what lets every hook judging it log its plain allow once.
LOG_CALL = "call"
#: Beside the log, one empty file per tool call already logged: whichever hook creates it writes the line.
LOG_CLAIMS = ".calls"
#: A plain allowed tool call's one line is the call's, never one policy's: these fields of its hook are left out.
_LOG_PER_HOOK = ("policy_id", "plugin", "plugin_version", "kind", "match_count", "matches", "rules")
#: A claim outlives every hook of its call (each runs within its client's timeout), then is pruned.
LOG_CLAIM_SECONDS = 600
#: A claim whose name starts with this prunes the old ones: about one claim in 16.
_LOG_CLAIM_PRUNER = "0"
_LOG_CLAIM_NAME = 32
#: A lone surrogate (a path that was not UTF-8) cannot be encoded: it is written as the text `\uXXXX`.
_LOG_SURROGATE = re.compile("[\ud800-\udfff]")
#: The scan-secrets policy's content_pattern, vendored: a debug trace never carries a value it would block.
_LOG_SECRET_RE = re.compile(
    r"""(?i)((AKIA|ASIA)[0-9A-Z]{16}|gh[oprsu]_[0-9A-Za-z]{36}|github_pat_[0-9A-Za-z_]{22,}|xox[bpas]-[0-9A-Za-z-]{10,}|(sk|rk)_live_[0-9A-Za-z]{16,}|sk-proj-[0-9A-Za-z_-]{20,}|sk-ant-[0-9A-Za-z_-]{20,}|sk-[0-9A-Za-z]{20,}|AIza[0-9A-Za-z_-]{35}|npm_[0-9A-Za-z]{36}|SG\.[0-9A-Za-z_-]{16,}\.[0-9A-Za-z_-]{16,}|eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*|-----BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----|api[_-]?key\s*=\s*["'][A-Za-z0-9_\-]{20,}["']|secret[_-]?key\s*=\s*["'][A-Za-z0-9_\-]{20,}["']|auth[_-]?token\s*=\s*["'][A-Za-z0-9_\-]{20,}["']|password\s*=\s*["'][^"'\s]{12,}["']|(api|secret|auth)[_-]?(key|token)\s*[=:]\s*[A-Za-z0-9_\-]{20,}|password\s*[=:]\s*[^\s"'${}]{12,})"""
)
_LOG_BYTES_RANGE = "a whole number from 65536 (64 KiB) to 1073741824 (1 GiB)"
#: How long a writer waits for the chain's lock before it writes its line unchained; held for one read and one write.
LOG_CHAIN_WAIT = 1.0
_LOG_CHAIN_POLL = 0.0002


def log_settings_read(path):
    """(the valid settings in one scope's file, what is wrong with it); a missing file is ({}, [])."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, []
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return {}, [f"{path}: unreadable or not JSON ({exc})"]
    if not isinstance(doc, dict):
        return {}, [f"{path}: must be a JSON object with level and/or max_bytes"]
    found, problems = {}, []
    level, size = doc.get("level"), doc.get("max_bytes")
    if level in LOG_LEVELS:
        found["level"] = level
    elif level is not None:
        problems.append(f"{path}: level must be off, info or debug, not {level!r}")
    if type(size) is int and LOG_MIN_MAX_BYTES <= size <= LOG_MAX_MAX_BYTES:
        found["max_bytes"] = size
    elif size is not None:
        problems.append(f"{path}: max_bytes must be {_LOG_BYTES_RANGE}, not {size!r}; using the next scope or 1048576")
    unknown = sorted(set(doc) - set(LOG_SETTINGS_KEYS))
    if unknown:
        problems.append(f"{path}: unknown key(s) {', '.join(map(str, unknown))}; only level and max_bytes are read")
    return found, problems


def log_settings_paths(repo_root):
    """The settings files in precedence order: the repository's (when known), then the user's."""
    repo = [Path(repo_root).joinpath(*LOG_SETTINGS_PARTS)] if repo_root is not None else []
    return [*repo, Path(os.path.expanduser("~")).joinpath(*LOG_SETTINGS_PARTS)]


def log_env_level():
    """The level the hook's own environment sets, or None: the legacy switch, then `CHOCK_LOG_LEVEL`."""
    if os.environ.get(LOG_LEGACY_ENV) == "0":
        return LOG_OFF
    named = os.environ.get(LOG_LEVEL_ENV, "").strip().lower()
    return named if named in LOG_LEVELS else None


def log_settings(repo_root):
    """(level, max_bytes) in force: the environment, then the repository's file, the user's, then info and 1 MiB."""
    scopes = [log_settings_read(path)[0] for path in log_settings_paths(repo_root)]
    level = log_env_level() or next((s["level"] for s in scopes if "level" in s), LOG_INFO)
    size = next((s["max_bytes"] for s in scopes if "max_bytes" in s), LOG_DEFAULT_MAX_BYTES)
    return level, size


def log_record_level(record):
    """`debug` for a plain allow, `info` for every decision a policy made, something let through, or an agent's action."""
    plain = record.get("verdict") == LOG_ALLOW and not any(key in record for key in LOG_LET_THROUGH)
    return LOG_DEBUG if plain else LOG_INFO


def log_plain_action(record):
    """Whether `record` is an agent's action that every policy let through untouched: one line per tool call."""
    untouched = not any(key in record for key in LOG_LET_THROUGH if key != "target")
    return record.get("verdict") == LOG_ALLOW and "target" in record and untouched


def _log_prune_claims(folder):
    cutoff = datetime.now(timezone.utc).timestamp() - LOG_CLAIM_SECONDS
    for claim in folder.iterdir():
        try:
            if claim.stat().st_mtime < cutoff:
                claim.unlink()
        except OSError:
            continue


def log_claim(path, record, call):
    """True for the first hook to log this tool call's plain allow; False for every later one. Fails open.

    The call is the client's `tool_use_id`, else (session, second, target): identical calls in one second are one.
    """
    key = "\0".join((str(record.get("session_id")), str(record.get("target")), call or log_now()))
    name = hashlib.sha256(key.encode("utf-8", "backslashreplace")).hexdigest()[:_LOG_CLAIM_NAME]
    folder = Path(path).parent / LOG_CLAIMS
    try:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.close(os.open(str(folder / name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    except FileExistsError:
        return False
    except OSError:
        return True  # no claim to be had: a duplicate line beats a lost one
    if name.startswith(_LOG_CLAIM_PRUNER):
        _log_prune_claims(folder)
    return True


def log_now():
    """The UTC time to the second, as every line is stamped."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_admits(level, record_level):
    """Whether a record of `record_level` is written at `level`."""
    return level == LOG_DEBUG or (level == LOG_INFO and record_level == LOG_INFO)


def log_redact(text):
    """`text` with every value scan-secrets would block replaced."""
    return _LOG_SECRET_RE.sub(LOG_REDACTED, str(text))


def log_trace_text(text):
    """`text` with every value scan-secrets would block replaced, then cut to `LOG_TRACE_CAP` characters."""
    redacted = log_redact(text)
    return redacted if len(redacted) <= LOG_TRACE_CAP else redacted[:LOG_TRACE_CAP] + "..."


def log_windows():
    """Whether this is Windows, whose lock is msvcrt's rather than fcntl's."""
    return os.name == "nt"


def log_lock(fd):
    """Take a non-blocking exclusive lock on `fd` (msvcrt on Windows, fcntl elsewhere); False when it is held."""
    try:
        if log_windows():
            import msvcrt  # noqa: PLC0415 -- the platform's own lock, imported where it exists

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl  # noqa: PLC0415 -- the platform's own lock, imported where it exists

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ImportError):
        return False
    return True


def log_unlock(fd):
    """Release `log_lock`'s lock; closing the descriptor releases an fcntl lock on its own."""
    if log_windows():
        try:
            import msvcrt  # noqa: PLC0415 -- the platform's own lock, imported where it exists

            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except (OSError, ImportError):
            return


def _log_lock_wait(fd):
    """Take `log_lock`'s lock on `fd`, waiting up to `LOG_CHAIN_WAIT` seconds; False when it stays held."""
    deadline = time.monotonic() + LOG_CHAIN_WAIT
    while not log_lock(fd):
        if time.monotonic() >= deadline:
            return False
        time.sleep(_LOG_CHAIN_POLL)
    return True


def _log_rotate_held(path, max_bytes):
    """Move a file past `max_bytes` to `log_rotated(path)`; the caller holds the chain's lock. A failed move waits."""
    try:
        if path.stat().st_size > max_bytes:
            path.replace(log_rotated(path))
    except OSError:
        return


def _log_line(path, stamped, *, held):
    """`stamped` as one line's bytes, chained after the last line (or the rotated file's) when the lock is `held`.

    A line that cannot be chained names why (`unchained`); a torn last line (no newline) is closed, never joined.
    """
    try:
        last, torn = log_tail(path)
        if held:
            stamped = {**stamped, **log_chain_after(last or log_last_line(log_rotated(path)))}
        else:
            stamped = {**stamped, LOG_CHAIN_UNCHAINED: "lock"}
    except (OSError, ValueError):
        torn = False
        stamped = {**stamped, LOG_CHAIN_UNCHAINED: "unreadable" if held else "lock"}
    text = _LOG_SURROGATE.sub(lambda found: f"\\\\u{ord(found[0]):04x}", json.dumps(stamped, ensure_ascii=False))
    line = (text + "\n").encode("utf-8")
    return b"\n" + line if torn else line


def log_append(path, record, max_bytes=LOG_DEFAULT_MAX_BYTES):
    """Append one stamped, chained, complete line to `path` in a single write, under the chain's lock.

    Each line names the sha256 of the line before it (`prev`) and its place (`seq`); the first line after a
    rotation names the rotated file's last. A writer that cannot take the lock writes its line `unchained`.
    """
    path = Path(path)
    log_require_safe(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = {"ts": log_now(), **{k: v for k, v in record.items() if k not in LOG_CHAIN_KEYS}}
    lock = os.open(str(path) + ".lock", os.O_RDWR | os.O_CREAT | LOG_OPEN_FLAGS, 0o600)
    try:
        held = _log_lock_wait(lock)
        try:
            if held:
                _log_rotate_held(path, max_bytes)
            line = _log_line(path, stamped, held=held)
            fd = os.open(
                str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0) | LOG_OPEN_FLAGS, 0o600
            )
            try:
                os.write(fd, line)
            finally:
                os.close(fd)
        finally:
            if held:
                log_unlock(lock)
    finally:
        os.close(lock)


def log_write(path, record, repo_root):
    """Write `record` to `path` when the level in force for `repo_root` admits it, stamped with its level. Raises on I/O.

    A plain allowed action is written once per tool call (`call`, never itself written), by the first hook and
    naming no policy; at debug every later hook still writes its own line.
    """
    level, size = log_settings(repo_root)
    record = dict(record)
    call = record.pop(LOG_CALL, None)
    record_level = log_record_level(record)
    kept = "would_action" in record and os.environ.get(LOG_LEGACY_ENV) == "0"  # the legacy switch kept rollout evidence
    if not (kept or log_admits(level, record_level)):
        return
    if log_plain_action(record):
        if log_claim(path, record, call):
            record = {key: value for key, value in record.items() if key not in _LOG_PER_HOOK}
        elif level == LOG_INFO:
            return
    log_append(path, {**record, "level": record_level}, size)


#: A person's stop for one repository: local state, never committed (`chock init` ignores it).
HALT_PARTS = (".chock", "stop.json")
HALT_ALL = "all"
#: The decision log's reason for every call a stop refused.
HALT_REASON = "stopped"
#: The policy id the log files a refusal under when no policy's hook made it, and the stop and resume lines.
HALT_POLICY = "chock-stop"
#: A client id as `--agent` takes it and a scope is written: anything else reads as every agent.
HALT_CLIENT_RE = re.compile(r"^[a-z0-9_]{1,32}$")
#: The runtime flag of the repo stop's own pre-tool hook, which `chock sync` wires for every client.
HALT_HOOK_FLAG = "--stop-check"
#: Every in-agent client id (`chock.vendors.in_agent_vendors()`, pinned by a test): a git marker naming
#: none of them cannot be told apart from a stopped client, so any stop reaches it.
HALT_CLIENTS = (
    "antigravity",
    "claude_code",
    "codex_cli",
    "cursor",
    "devin",
    "factory_droid",
    "gemini_cli",
    "goose",
    "grok",
    "mistral_vibe",
    "openhands",
    "tabnine",
    "vscode_copilot",
    "windsurf",
)
#: The machine-level registry under the person's home: one `<sha256 of the repository's realpath>.json` per stop,
#: so a runtime that cannot tell which repository its session is rooted in still sees every stop on the machine.
HALT_REGISTRY_PARTS = (".chock", "stops")
_HALT_REGISTRY_SUFFIX = ".json"
#: The machine-wide stop (`chock stop --everywhere`) in the registry: no sha256 hex digest starts with `_`.
HALT_EVERYWHERE_NAME = "_everywhere.json"
_HALT_EVERYWHERE_UNREADABLE = "~/.chock/stops/_everywhere.json exists but cannot be read, so every agent is refused"
_HALT_REGISTRY_UNREADABLE = "~/.chock/stops exists but cannot be read, so every agent is refused"
_HALT_GITDIR = "gitdir:"
_HALT_REASON_CAP = 200
_HALT_UNREADABLE = ".chock/stop.json exists but cannot be read, so every agent is refused"
_HALT_NO_REASON = "no reason given"
#: Platforms whose default filesystem ignores case: a path typed in another case names the same repository.
_HALT_CASELESS = ("darwin", "win32", "cygwin")


def _halt_read_file(path, unreadable):
    """The stop `path` holds as {scope, reason, ...}, or None when there is no file. A file that exists but
    cannot be read or parsed, or names no valid scope, stops every agent: fail closed."""
    stopped = {"scope": HALT_ALL, "reason": unreadable, "unreadable": True}
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError):
        return stopped if os.path.lexists(path) else None
    except (OSError, UnicodeError, ValueError):
        return stopped
    scope = doc.get("scope") if isinstance(doc, dict) else None
    if not isinstance(scope, str) or not (scope == HALT_ALL or HALT_CLIENT_RE.match(scope)):
        return stopped
    reason = doc.get("reason")
    return {**doc, "scope": scope, "reason": reason if isinstance(reason, str) else ""}


def halt_read(repo_root):
    """The stop in force for `repo_root`, or None; read fail-closed."""
    if repo_root is None:
        return None
    return _halt_read_file(Path(repo_root).joinpath(*HALT_PARTS), _HALT_UNREADABLE)


def halt_registry_dir():
    """`~/.chock/stops`: the machine-level registry of every stop in force."""
    return Path(os.path.expanduser("~")).joinpath(*HALT_REGISTRY_PARTS)


def halt_norm(path):
    """`path`'s realpath, casefolded where the filesystem ignores case (realpath keeps the case it was typed in)."""
    real = os.path.realpath(str(path))
    return real.casefold() if sys.platform in _HALT_CASELESS else real


def halt_registry_entry(repo_root):
    """The registry entry for `repo_root`, named by the sha256 of its normalised realpath."""
    key = hashlib.sha256(halt_norm(repo_root).encode("utf-8")).hexdigest()
    return halt_registry_dir() / f"{key}{_HALT_REGISTRY_SUFFIX}"


def halt_everywhere_entry():
    """`~/.chock/stops/_everywhere.json`: the machine-wide stop."""
    return halt_registry_dir() / HALT_EVERYWHERE_NAME


def halt_everywhere_read():
    """The machine-wide stop, reaching every agent whatever its scope says, or None. A file there that is not a
    regular one, or cannot be read or parsed, stops every agent: fail closed."""
    path = halt_everywhere_entry()
    if not os.path.lexists(path):
        return None
    unreadable = {"scope": HALT_ALL, "reason": _HALT_EVERYWHERE_UNREADABLE, "unreadable": True}
    regular = os.path.isfile(path) and not os.path.islink(path)
    stop = _halt_read_file(path, _HALT_EVERYWHERE_UNREADABLE) if regular else unreadable
    return {**(stop or unreadable), "scope": HALT_ALL, "everywhere": True}


def halt_registry_find(client, repos=None):
    """The machine-wide stop, else the first registry entry that reaches `client` (only those for `repos`, when
    given), or None. A registry that exists but cannot be listed, or an entry that cannot be read, refuses."""
    folder = halt_registry_dir()
    unreadable = {"scope": HALT_ALL, "reason": _HALT_REGISTRY_UNREADABLE, "unreadable": True}
    try:
        names = sorted(os.listdir(folder))
    except (FileNotFoundError, NotADirectoryError):
        return unreadable if os.path.lexists(folder) else None
    except OSError:
        return unreadable
    everywhere = halt_everywhere_read() if HALT_EVERYWHERE_NAME in names else None
    if everywhere is not None:
        return everywhere
    wanted = None if repos is None else {halt_registry_entry(repo).name for repo in repos}
    for name in names:
        if not name.endswith(_HALT_REGISTRY_SUFFIX) or (wanted is not None and name not in wanted):
            continue
        stop = _halt_read_file(folder / name, _HALT_REGISTRY_UNREADABLE)
        if stop is not None and halt_covers(stop, client):
            return stop
    return None


def halt_main_root(repo_root):
    """The main worktree of the linked worktree at `repo_root` (its `.git` is a file naming a gitdir whose
    `commondir` leads to the main `.git`), or the bare repository itself that holds it, else None. Read from
    disk: the runtime cannot wait on git."""
    dot = Path(repo_root) / ".git"
    try:
        text = dot.read_text(encoding="utf-8").strip() if dot.is_file() else ""
        if not text.startswith(_HALT_GITDIR):
            return None
        gitdir = Path(repo_root) / text[len(_HALT_GITDIR) :].strip()  # an absolute gitdir replaces the root
        common = gitdir.joinpath("commondir").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None  # a submodule's gitdir has no commondir: it is no linked worktree
    common_dir = Path(os.path.realpath(gitdir / common))
    return common_dir.parent if common_dir.name == ".git" else common_dir


def halt_repos(path):
    """Every repository holding `path`, as spelled and with every symlink resolved, nearest first: each folder up
    from it with a `.git`, nested ones included."""
    try:
        text = str(path)
        heres = dict.fromkeys(Path(found) for found in (os.path.abspath(text), os.path.realpath(text)))
    except (OSError, ValueError):
        return []
    folders = (folder for here in heres for folder in (here, *here.parents))
    return [folder for folder in dict.fromkeys(folders) if os.path.lexists(folder / ".git")]


def halt_find(roots, client):
    """The first stop in force over `roots`, or in the main worktree of any of them, that reaches `client`."""
    seen = []
    for root in roots:
        for folder in (root, halt_main_root(root)):
            if folder is None or folder in seen:
                continue
            seen.append(folder)
            stop = halt_read(folder)
            if stop is not None and halt_covers(stop, client):
                return stop
    return None


def _halt_client(name):
    return str(name or "").strip().lower().replace("-", "_")


def _halt_names(client, named):
    """Whether `client` (from a marker or a bundle) names the client id `named`, or a shorter form of it."""
    return client.startswith(named) or named.startswith(client + "_")


def halt_covers(stop, client):
    """Whether `stop` reaches `client`: every agent, or the one named (`cursor_agent` is `cursor`'s; `codex` may
    be `codex_cli`). An agent naming no client, or one no in-agent client id matches, is reached: fail closed."""
    scope, client = _halt_client(stop.get("scope")), _halt_client(client)
    if scope == HALT_ALL or not client:
        return True
    return _halt_names(client, scope) or not any(_halt_names(client, known) for known in HALT_CLIENTS)


def halt_message(stop):
    """`stopped: <reason>`, the reason printable and capped, and the one way to lift it."""
    reason = "".join(ch for ch in str(stop.get("reason") or "") if ch.isprintable()).strip()
    reason = (reason or _HALT_NO_REASON)[:_HALT_REASON_CAP]
    if stop.get("everywhere"):
        return (
            f"{HALT_REASON}: {reason}. A person stopped every agent on this machine (`chock stop --everywhere`); "
            "every tool call is refused until they run `chock resume --everywhere`."
        )
    return (
        f"{HALT_REASON}: {reason}. A person stopped agents in this repository (`chock stop`); "
        "every tool call is refused until they run `chock resume`."
    )


def halt_git_roots(repo_root: Path) -> list[Path]:
    """Every folder whose stop reaches a git command, as the git dispatcher finds them: the work tree
    (`GIT_WORK_TREE` too), the checkout of the git dir and of the common dir (a bare repository is its own),
    and every folder above each, symlinks resolved."""
    named = [
        Path(repo_root),
        *(Path(os.environ[name]) for name in ("GIT_WORK_TREE", "GIT_DIR") if os.environ.get(name)),
    ]
    try:
        shown = subprocess.run(
            ["git", "rev-parse", "--absolute-git-dir", "--git-common-dir"],  # noqa: S607
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
        dirs = shown.stdout.splitlines() if shown.returncode == 0 else []
    except (OSError, subprocess.SubprocessError, UnicodeError):
        dirs = []
    for found in (Path(os.path.realpath(line)) for line in dirs if line):
        named.append(found.parent if found.name == ".git" else found)
    heres = (Path(spelled(str(path))) for path in named for spelled in (os.path.abspath, os.path.realpath))
    return list(dict.fromkeys(folder for here in heres for folder in (here, *here.parents)))


class ListingError(Exception):
    """A git path listing the runner could not read: the gate refuses rather than judge a change it cannot see."""


class DiffError(ListingError):
    """A `git diff` the runner could not read or parse: the gate refuses rather than judge part of a change."""


#: Lines git writes between `diff --git` and a file's first hunk.
_DIFF_HEADERS = (
    "old mode ",
    "new mode ",
    "deleted file mode ",
    "new file mode ",
    "copy from ",
    "copy to ",
    "rename from ",
    "rename to ",
    "similarity index ",
    "dissimilarity index ",
    "index ",
    "--- ",
    "+++ ",
    "Binary files ",
)
_HUNK_RE = re.compile(r"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")


def _hunk_line(line: str, old: int, new: int, sides: tuple[list[str], list[str]]) -> tuple[int, int]:
    """Place one line inside a hunk by its first character; returns the counts still owed."""
    mark, content = line[:1], line[1:]
    if mark == "+" and new:
        sides[0].extend(content.splitlines() or [""])
        return old, new - 1
    if mark == "-" and old:
        sides[1].extend(content.splitlines() or [""])
        return old - 1, new
    if mark == " " and old and new:
        return old - 1, new - 1
    if mark == "\\":
        return old, new
    msg = f"git diff has a hunk line it cannot place: {line[:40]!r}"
    raise DiffError(msg)


def _diff_sides(text: str) -> tuple[list[str], list[str]]:
    """(added, removed) lines of a unified diff. Headers only before a file's first hunk; inside one, the
    first character classifies a line and the hunk's counts bound it. Raises DiffError on anything else."""
    if text and not text.endswith("\n"):
        msg = "git diff does not end with a newline"
        raise DiffError(msg)
    sides: tuple[list[str], list[str]] = ([], [])
    old = new = 0
    in_file = False
    for line in text.split("\n")[:-1]:
        hunk = _HUNK_RE.match(line)
        if old or new:
            old, new = _hunk_line(line, old, new, sides)
        elif line.startswith("diff --git "):
            in_file = True
        elif in_file and hunk:
            old, new = (int(n) if n is not None else 1 for n in hunk.groups())
        elif not (in_file and line.startswith((*_DIFF_HEADERS, "\\"))):
            msg = f"git diff has a line outside any hunk: {line[:40]!r}"
            raise DiffError(msg)
    if old or new:
        msg = "git diff ends inside a hunk"
        raise DiffError(msg)
    return sides


def _nul_paths(out: bytes) -> list[str]:
    """Paths from a `-z` listing, verbatim. Raises ListingError on anything but NUL-terminated UTF-8 entries."""
    if not out:
        return []
    entries = out.split(b"\0")
    if entries.pop() or not all(entries):
        msg = "git listed paths that are not NUL-terminated"
        raise ListingError(msg)
    try:
        return [entry.decode("utf-8") for entry in entries]
    except UnicodeDecodeError as exc:
        msg = f"git listed a path that is not UTF-8 ({exc.reason})"
        raise ListingError(msg) from exc


#: Each line names the sha256 of the line before it (`prev`, its exact bytes without the newline) and its place (`seq`).
LOG_CHAIN_PREV, LOG_CHAIN_SEQ = "prev", "seq"
#: A line written outside the chain names why (`lock`: the lock stayed held; `unreadable`: the last line could not be read).
LOG_CHAIN_UNCHAINED = "unchained"
LOG_CHAIN_KEYS = (LOG_CHAIN_PREV, LOG_CHAIN_SEQ, LOG_CHAIN_UNCHAINED)
#: The `prev` of the first line a log ever had: no line came before it.
LOG_CHAIN_GENESIS = "0" * 64
#: How far back from a log's end its last line is looked for before the whole file is read.
_LOG_TAIL_BYTES = 65_536

#: `st_mode`'s file-type bits and the two types a log's files and directories may be (`stat.S_IFMT`, `S_IFREG`, `S_IFDIR`).
LOG_MODE_MASK, LOG_MODE_FILE, LOG_MODE_DIR = 0o170000, 0o100000, 0o040000
LOG_UNSAFE = "not a regular file in real directories; refusing to open it"
#: Opening a log never follows a symlink and never waits on a FIFO.
LOG_OPEN_FLAGS = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)


def log_rotated(path):
    """Where `log_append` moves a full log: `<stem>.1<suffix>` beside it."""
    path = Path(path)
    return path.with_name(path.stem + ".1" + path.suffix)


def log_tail(path):
    """(the last line of `path` as bytes without its newline or None, whether the file ends without a newline)."""
    try:
        with open(path, "rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            fh.seek(max(0, size - _LOG_TAIL_BYTES))
            tail = fh.read()
            if b"\n" not in tail.rstrip(b"\n") and size > len(tail):
                fh.seek(0)
                tail = fh.read()  # one line longer than the tail read: read the whole file
    except FileNotFoundError:
        return None, False
    last = tail.rstrip(b"\n").rsplit(b"\n", 1)[-1]
    return last or None, bool(tail) and not tail.endswith(b"\n")


def log_last_line(path):
    """The last line of `path` as bytes, without its newline; None for a missing or empty file."""
    return log_tail(path)[0]


def log_line_hash(line):
    """The chain's link to a line: the sha256 of its exact bytes, without the newline."""
    return hashlib.sha256(line).hexdigest()


def log_line_seq(line):
    """A line's place in its chain, or -1 when it carries none (an unchained or unreadable line)."""
    try:
        seq = json.loads(line).get(LOG_CHAIN_SEQ)
    except (ValueError, AttributeError):
        return -1
    return seq if type(seq) is int else -1


def log_chain_after(last):
    """The chain fields of the line after `last` (bytes); the genesis when no line came before."""
    if last is None:
        return {LOG_CHAIN_SEQ: 0, LOG_CHAIN_PREV: LOG_CHAIN_GENESIS}
    return {LOG_CHAIN_SEQ: log_line_seq(last) + 1, LOG_CHAIN_PREV: log_line_hash(last)}


def log_path_safe(path):
    """Whether the log, its lock and rotated file are regular files or absent, and its two directories real directories.

    lstat, so a symlink, FIFO, socket or device is refused before anything opens it: opening a FIFO blocks the hook
    until its timeout, which a client may read as an allow.
    """
    path = Path(path)
    checks = (
        (path, LOG_MODE_FILE),
        (Path(str(path) + ".lock"), LOG_MODE_FILE),
        (log_rotated(path), LOG_MODE_FILE),
        (path.parent, LOG_MODE_DIR),
        (path.parent.parent, LOG_MODE_DIR),
    )
    for target, kind in checks:
        try:
            mode = os.lstat(target).st_mode
        except FileNotFoundError:
            continue
        except OSError:
            return False
        if mode & LOG_MODE_MASK != kind:
            return False
    return True


def log_require_safe(path):
    """Raise OSError unless `log_path_safe(path)`."""
    if not log_path_safe(path):
        raise OSError(LOG_UNSAFE)


#: The git hook a merge's own commit runs: judged as a commit.
_MERGE_COMMIT = "pre-merge-commit"


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


def _log_fields(raw: str) -> dict | None:
    """What the hook handler gives this call's decision line (session_id, actor, target), if any."""
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return None
    fields = payload.get("log") if isinstance(payload, dict) else None
    return fields if isinstance(fields, dict) else None


def _writes(raw: str) -> dict[str, str]:
    """The files this event puts under judgement, whole."""
    return _texts(raw, "writes")


#: An agent event whose stdin is not UTF-8 is refused, never read with replacement characters in its place.
_EXIT_UNDECODABLE = 2


def _agent_stdin() -> str | None:
    """The agent event's stdin as UTF-8 text, or None when its bytes do not decode."""
    try:
        return sys.stdin.buffer.read().decode("utf-8")
    except UnicodeDecodeError:
        return None


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
    stop_p = sub.add_parser("stop-check", help="Refuse an agent's commit or push while `chock stop` is in force")
    stop_p.add_argument("--event", required=True, choices=[*_GIT_EVENTS, _MERGE_COMMIT])
    args = parser.parse_args(argv)

    if args.command == "stop-check":
        halted = halt_git(_repo_root(), "pre-commit" if args.event == _MERGE_COMMIT else args.event)
        return 0 if halted is None else halted[0]

    if args.command == "script-verdict":
        return script_verdict(args.policy, args.event, args.code, _repo_root())

    if args.event == "ci" and not args.base:
        parser.error("--event ci requires --base")

    if args.event in AGENT_EVENTS:
        # The files are on stdin because a tool call's content is not in the repository yet and
        # cannot be read back from it. {"writes": {"<path>": "<text>"}, "added": {"<path>": "<text>"}},
        # `added` present only for an edit, carrying the text it introduces.
        # Paths are named from the directory the runtime works in, which may sit below the git top-level.
        raw = _agent_stdin()
        if raw is None:
            print(
                "chock: the hook payload on stdin is not UTF-8; refusing rather than judging a guess", file=sys.stderr
            )
            return _EXIT_UNDECODABLE
        return run(
            Path(args.gate),
            args.event,
            None,
            Path.cwd(),
            writes=_writes(raw),
            added=_texts(raw, "added"),
            session=_session(raw),
            fields=_log_fields(raw),
        )

    push_stdin = sys.stdin.read() if args.event == "pre-push" and not sys.stdin.isatty() else None
    return run(Path(args.gate), args.event, push_stdin, _repo_root(), base=args.base, head_ref=args.head_ref)


if __name__ == "__main__":
    raise SystemExit(main())

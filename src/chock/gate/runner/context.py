"""Gate runner: the verdict record and the git- or write-backed material a kind judges."""

from __future__ import annotations

import difflib
import fnmatch
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .constants import _PUSH_LINE_MIN_PARTS

# >>> gate.py 01
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

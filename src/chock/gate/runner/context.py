"""Gate runner: the verdict record and the git- or write-backed material a kind judges."""

from __future__ import annotations

import contextlib
import fnmatch
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .constants import _PUSH_LINE_MIN_PARTS, CASE_BLIND_PLATFORMS
from .gitparse import DiffError, ListingError, _diff_chunks, _diff_sides, _nul_paths, cancel_moved

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
        *,
        case_blind: bool | None = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        #: Whether paths and scope globs compare without regard to case; the platform's default unless told.
        self.case_blind = sys.platform in CASE_BLIND_PLATFORMS if case_blind is None else case_blind
        #: The session-log handle a script gate receives; None when the hook named no session.
        self.session = dict(session) if session else None
        self._push_stdin = push_stdin or ""
        self.base = base
        self.head_ref = head_ref
        #: The policy's applies_to.paths. Empty means every changed file is in scope.
        self.scope = tuple(scope or ())
        #: Path prefixes this gate never judges: its own policy's source and compiled folders.
        self.own = tuple(own)
        self._rename_map: dict[str, str] | None = None
        self._moved: dict[str, tuple[list[str], list[str]]] | None = None

    def is_own(self, path: str) -> bool:
        """Whether `path` is in this policy's own source or compiled folder."""
        return bool(self.own) and path.startswith(self.own)

    def in_scope(self, path: str, *, judge_own: bool = False) -> bool:
        """Whether this policy may judge this file at all.

        fnmatch semantics, so `*` crosses `/` and `.github/workflows/*` covers nested files.
        A gate with no scope sees every changed file, which is what every gate did before
        applies_to.paths was read.
        """
        if not judge_own and self.is_own(path):
            return False
        if _is_outside(path):
            return True
        if self.case_blind:
            return not self.scope or any(fnmatch.fnmatchcase(path.casefold(), g.casefold()) for g in self.scope)
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

    def staged_paths(self, diff_filter: str = "ACMRT", *, judge_own: bool = False) -> list[str]:
        paths = self._listing("diff", *self._range(), "--name-only", f"--diff-filter={diff_filter}")
        return [path for path in paths if self.in_scope(path, judge_own=judge_own)]

    def _rename_range(self) -> list[str] | None:
        """The git-diff scope whose renames the baseline follows; None when this context has none."""
        return self._range()

    def _renames(self) -> dict[str, str]:
        """{new path: old path} for what git itself reports as renamed (`-M`, default similarity); never a guess.

        A listing that fails or does not parse says no rename, which leaves the baseline at the path (stricter).
        """
        if self._rename_map is None:
            scope, tokens = self._rename_range(), []
            if scope is not None:
                with contextlib.suppress(ListingError):
                    tokens = self._listing("diff", *scope, "-M", "--relative", "--name-status", "--diff-filter=R")
            self._rename_map = {tokens[i + 2]: tokens[i + 1] for i in range(0, len(tokens) - 2, 3)}
        return self._rename_map

    def _git_diff(self, *args: str) -> str:
        """`git diff` over `args`, as git writes it; raises DiffError when git fails."""
        try:
            proc = subprocess.run(  # noqa: S603 -- reading repo facts via git is this class's whole job
                [_GIT, "--literal-pathspecs", "diff", *args],
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

    def _diff_args(self) -> list[str]:
        """What `git diff` takes to show the whole change, renames followed, no hunk context."""
        return [*self._range(), "-M", "-U0", "--no-color", "--no-ext-diff", "--no-textconv"]

    def _change_paths(self) -> list[str]:
        """Every path the change touches, in the order `git diff` shows them."""
        return self._listing("diff", *self._range(), "-M", "--name-only")

    def _diff_text(self, path: str) -> str:
        """`path`'s `-U0` diff as git writes it, unconverted; raises DiffError when git fails."""
        old = self._renames().get(path)
        return self._git_diff(*self._diff_args(), "--", *((path, old) if old else (path,)))

    def _moves_cancelled(self) -> dict[str, tuple[list[str], list[str]]]:
        """{path: (added, removed)} of the whole change with the lines it only moves or re-indents cancelled.

        Empty when git's diff and its path listing disagree on the files, which leaves every line counted.
        """
        if self._moved is None:
            try:
                paths = self._change_paths()
            except ListingError as exc:
                raise DiffError(str(exc)) from exc
            chunks = _diff_chunks(self._git_diff(*self._diff_args()))
            self._moved = {}
            if len(paths) == len(chunks):
                sides = cancel_moved([_diff_sides(chunk) for chunk in chunks])
                self._moved = dict(zip(paths, sides, strict=True))
        return self._moved

    def added_lines(self, path: str) -> list[str]:
        moved = self._moves_cancelled().get(path)
        return moved[0] if moved else _diff_sides(self._diff_text(path))[0]

    def removed_lines(self, path: str) -> list[str]:
        """The deleted side of the diff -- what a test-weakening change takes away."""
        moved = self._moves_cancelled().get(path)
        return moved[1] if moved else _diff_sides(self._diff_text(path))[1]

    def staged_blob(self, path: str) -> str:
        """The proposed content: staged in index mode, committed at HEAD in range mode."""
        return self._git("show", f"HEAD:{path}" if self.base else f":{path}")

    def renamed_from(self, path: str) -> str:  # the old path git reports, else `path`
        return self._renames().get(path, path)

    def head_blob(self, path: str) -> str:
        """Content before the change ("" when new); a renamed path reads its old path."""
        return self._git("show", f"{self.base or 'HEAD'}:{self.renamed_from(path)}")

    def committed_blob(self, path: str) -> str:
        """The file as HEAD has it, or "" when HEAD does not."""
        return self._git("show", f"HEAD:{path}")

    def net_added_lines(self, path: str) -> list[str]:
        """The lines this change introduces: at a commit, `added_lines`."""
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

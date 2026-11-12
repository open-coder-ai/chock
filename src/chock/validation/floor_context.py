"""The material a gate judges at the floor: the tree diff base..head, read by revision, never from the working tree."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from chock.gate.runner import GateContext
from chock.gate.runner.context import _GIT
from chock.gate.runner.gitparse import DiffError, _diff_sides


class FloorContext(GateContext):
    """`base..head` as the change; the head's files as the proposal; the base's as what a waiver must already be in.

    Every read is a `git show <rev>:<path>`, so a head file is data and never reaches a program as code.
    Diffs run with `--text` and `--no-renames`, so neither a NUL byte, a head `.gitattributes` nor a rename
    hides a line or a deletion. A control-plane path is never judged here: the control-plane rule owns it.
    """

    def __init__(  # noqa: PLR0913 -- the range and what it excludes, beside GateContext's own
        self,
        repo_root: Path,
        *,
        base: str,
        head: str,
        head_ref: str | None,
        scope: Sequence[str] | None,
        control_plane: Callable[[str], bool],
    ) -> None:
        super().__init__(repo_root=repo_root, base=base, head_ref=head_ref, scope=scope)
        self.head = head
        self.control_plane = control_plane

    def in_scope(self, path: str, *, judge_own: bool = False) -> bool:
        return not self.control_plane(path) and super().in_scope(path, judge_own=judge_own)

    def _range(self) -> list[str]:
        return ["--no-renames", str(self.base), self.head]

    def _diff_text(self, path: str) -> str:
        args = ("diff", *self._range(), "--text", "-U0", "--no-color", "--no-ext-diff", "--no-textconv", "--", path)
        try:
            proc = subprocess.run(  # noqa: S603 -- reading committed revisions is this class's whole job
                [_GIT, "--literal-pathspecs", *args], cwd=str(self.repo_root), capture_output=True, check=False
            )
        except OSError as exc:
            msg = f"git could not run ({exc})"
            raise DiffError(msg) from exc
        if proc.returncode:
            first = (proc.stderr.decode("utf-8", "replace").strip().splitlines() or [""])[0]
            msg = f"git diff failed (exit {proc.returncode}): {first}"
            raise DiffError(msg)
        return proc.stdout.decode("utf-8", "replace")

    def staged_blob(self, path: str) -> str:
        """The proposal: the file at the head."""
        return self._git("show", f"{self.head}:{path}")

    def head_blob(self, path: str) -> str:
        """Before the change: the file at the base."""
        return self._git("show", f"{self.base}:{path}")

    def committed_blob(self, path: str) -> str:
        """Where a waiver must be for the floor to honour it: the lines present and unchanged in both base and
        head. A line the pull request adds, changes or removes never carries a waiver, even a copy of a base line."""
        added, removed = _diff_sides(self._diff_text(path))
        touched = set(added) | set(removed)
        kept = set(self.staged_blob(path).splitlines())
        lines = self.head_blob(path).splitlines()
        return "\n".join(line for line in lines if line in kept and line not in touched)

    def current_branch(self) -> str:
        """The branch under test is the one named; the checkout's own branch is the base's, never the head's."""
        return self.head_ref or ""

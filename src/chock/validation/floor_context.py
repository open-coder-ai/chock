"""The material a gate judges at the floor: the base...head range, read by revision, never from the working tree."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from chock.gate.runner import GateContext
from chock.gate.runner.context import _GIT
from chock.gate.runner.gitparse import DiffError, _diff_sides


class FloorContext(GateContext):
    """`base...head` as the change; the head's files as the proposal; the base's as what a waiver must already be in.

    Every read is a `git show <rev>:<path>`, so a head file is data and never reaches a program as code.
    Diffs run with `--text`, so neither a NUL byte nor a head `.gitattributes` (`-diff`) hides added lines.
    A waiver counts only on a line the pull request leaves unchanged: no line it adds can carry one, even a
    copy of a line the base already has.
    """

    def __init__(  # noqa: PLR0913 -- the range's three revisions beside GateContext's own
        self,
        repo_root: Path,
        *,
        base: str,
        head: str,
        merge_base: str,
        head_ref: str | None,
        scope: Sequence[str] | None = None,
        own: Sequence[str] = (),
    ) -> None:
        super().__init__(repo_root=repo_root, base=base, head_ref=head_ref, scope=scope, own=own)
        self.head = head
        self.merge_base = merge_base

    def _range(self) -> list[str]:
        return [f"{self.base}...{self.head}"]

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
        """Before the change: the file at the merge-base, the same side the three-dot diff compares against."""
        return self._git("show", f"{self.merge_base}:{path}")

    def committed_blob(self, path: str) -> str:
        """Where a waiver must already be for the floor to honour it: the base's lines, less every line this
        pull request adds to `path` (an added line is changed by definition, so its waiver never counts)."""
        added = set(_diff_sides(self._diff_text(path))[0])
        lines = self._git("show", f"{self.base}:{path}").splitlines()
        return "\n".join(line for line in lines if line not in added)

    def current_branch(self) -> str:
        """The branch under test is the one named; the checkout's own branch is the base's, never the head's."""
        return self.head_ref or ""

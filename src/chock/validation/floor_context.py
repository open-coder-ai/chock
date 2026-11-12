"""The material a gate judges at the floor: the base...head range, read by revision, never from the working tree."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from chock.gate.runner import GateContext


class FloorContext(GateContext):
    """`base...head` as the change; the head's files as the proposal; the base's as what a waiver must already be in.

    Every read is a `git show <rev>:<path>`, so a head file is data and never reaches a program as code.
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

    def staged_blob(self, path: str) -> str:
        """The proposal: the file at the head."""
        return self._git("show", f"{self.head}:{path}")

    def head_blob(self, path: str) -> str:
        """Before the change: the file at the merge-base, the same side the three-dot diff compares against."""
        return self._git("show", f"{self.merge_base}:{path}")

    def committed_blob(self, path: str) -> str:
        """Where a waiver must already be for the floor to honour it: the file at the base."""
        return self._git("show", f"{self.base}:{path}")

    def current_branch(self) -> str:
        """The branch under test is the one named; the checkout's own branch is the base's, never the head's."""
        return self.head_ref or ""

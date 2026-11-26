"""Gate runner: the material a gate judges when an agent writes, shaped like a staged diff."""

from __future__ import annotations

import difflib
from collections.abc import Mapping, Sequence
from pathlib import Path

from .context import GateContext
from .gitparse import cancel_moved
from .headread import _head_show, _text_mode


# >>> gate.py 25
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
        case_blind: bool | None = None,
    ) -> None:
        super().__init__(repo_root=repo_root, scope=scope, own=own, session=session, case_blind=case_blind)
        self._writes = dict(writes)
        self._added = dict(added or {})
        self._stop = stop

    def _rename_range(self) -> list[str] | None:
        """At the turn's end, HEAD against the index and tree; a write before the tool runs has no rename."""
        return ["HEAD"] if self._stop else None

    def staged_paths(self, diff_filter: str = "ACMRT", *, judge_own: bool = False) -> list[str]:
        """Every write is a present file, so a filter asking only for deletions finds none."""
        if not set(diff_filter) & set("ACMRT"):
            return []
        return [path for path in self._writes if self.in_scope(path, judge_own=judge_own)]

    def staged_blob(self, path: str) -> str:
        return self._writes.get(path, "")

    def _diff(self, path: str) -> tuple[list[str], list[str]]:
        return cancel_moved(*_line_diff(self.head_blob(path), self._writes.get(path, "")))

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
        shown = _head_show(self.repo_root, f"./{path}")
        return "" if shown is None else _text_mode(shown, "replace")

    def head_blob(self, path: str) -> str:
        """The baseline: HEAD at the turn's end, else what is on disk now, which this write would replace."""
        if self._stop:
            return self.committed_blob(self.renamed_from(path))
        try:
            return (self.repo_root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

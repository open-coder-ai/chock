"""A policy's plugin enforcement: its shell guard, its tool_use gate, or both in one package.

A policy may ship both (catalog protect-agent-config: a guard for shell writes, a path gate
for Edit/Write). A package that carried only one would claim the policy while leaving the
other path open, so every hook-carrying store ships each half the vendor can run and states
exactly those halves. A gate the vendor cannot run is neither shipped nor claimed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chock.compile.emitters.in_agent import _guard_script, tool_use_gate_spec
from chock.plugin import gate_package

#: The guard notes' closing sentences repeat the gate note's; a combined note keeps the gate's.
_GUARD_NOTE_TAIL = " Repo-wide "
_GATE_NOTE_SUBJECT, _GATE_SUBJECT_AFTER_GUARD = "This policy ", "Its write gate "
_GUARD_LABEL, _GATE_LABEL = "Shell guard:", "Write gate:"


class PackageCollisionError(ValueError):
    """The guard's files and the gate's files would write different bytes to one package path."""


@dataclass(frozen=True)
class Halves:
    """The guard script name and the compiled tool_use gate a package carries, each optional."""

    script: str | None
    gate: dict[str, Any] | None

    @property
    def enforced(self) -> bool:
        return self.script is not None or self.gate is not None


def halves(vendor: str, policy_dir: Path, policy_id: str, repo_root: Path) -> Halves:
    """What `vendor`'s package of this policy carries: the guard if any, the gate if it reaches."""
    script = _guard_script(Path(policy_dir), policy_id)
    gate = tool_use_gate_spec(Path(policy_dir), Path(repo_root)) if gate_package.gate_reaches(vendor) else None
    return Halves(script, gate)


def merge_hooks(guard_doc: dict[str, Any] | None, gate_doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """One hooks document running both halves; either alone is returned unchanged."""
    if guard_doc is None or gate_doc is None:
        return guard_doc if gate_doc is None else gate_doc
    return _merge(guard_doc, gate_doc, "hooks")


def _merge(into: Any, other: Any, where: str) -> Any:
    """Concatenate entry lists, merge maps, and require agreement on everything else."""
    if isinstance(into, dict) and isinstance(other, dict):
        merged = dict(into)
        for key, value in other.items():
            merged[key] = _merge(into[key], value, f"{where}.{key}") if key in into else value
        return merged
    if isinstance(into, list) and isinstance(other, list):
        return into + other
    if into != other:
        msg = f"guard and gate hooks disagree at {where}: {into!r} vs {other!r}"
        raise PackageCollisionError(msg)
    return into


def place(files: dict[Path, str], extra: dict[Path, str]) -> None:
    """Add `extra` to `files`, refusing a path both already hold with different bytes."""
    for rel, content in extra.items():
        if rel in files and files[rel] != content:
            msg = f"two parts of the package write different bytes to {rel.as_posix()}"
            raise PackageCollisionError(msg)
        files[rel] = content


def skill_note(guard_note: str | None, gate_note: str | None) -> str | None:
    """The skill's enforcement note: one half's own, or the guard's lead then the gate's note."""
    if guard_note is None or gate_note is None:
        return guard_note if gate_note is None else gate_note
    lead = guard_note.split(_GUARD_NOTE_TAIL, 1)[0]
    return f"{lead} {gate_note.replace(_GATE_NOTE_SUBJECT, _GATE_SUBJECT_AFTER_GUARD, 1)}"


def posture(guard_posture: str, gate_posture: str, *, guard: bool, gate: bool) -> str:
    """The description's posture: each shipped half's own fail conditions, labelled when both ship."""
    if guard and gate:
        return f"{_GUARD_LABEL} {guard_posture} {_GATE_LABEL} {gate_posture}"
    return gate_posture if gate else guard_posture

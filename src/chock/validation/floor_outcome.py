"""What `chock check --floor` found: the refusals, undecided lines, notes and listed control-plane paths."""

from __future__ import annotations

from dataclasses import dataclass, field

from chock.validation import control_plane as cp


@dataclass
class Outcome:
    refusals: list[str] = field(default_factory=list)
    undecided: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    listed: list[str] = field(default_factory=list)
    mode: str = cp.REFUSE
    in_force: str = ""
    #: Listed paths that only a commit of the range changed; the tree diff leaves them as at the base.
    history_only: set[str] = field(default_factory=set)
    #: Listed path -> the any-depth pattern that matched it below the top level (the cost of matching at depth).
    deep: dict[str, str] = field(default_factory=dict)
    #: The base has no `.chock`: nothing was judged (V6).
    first_adoption: bool = False
    #: An error stopped the run before any verdict; `undecided` holds its one line.
    stopped: bool = False

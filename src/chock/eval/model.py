"""Case and result types shared by the eval runner's modes.

An outcome is deliberately five-valued, not two. `pending` and `skipped` are the honest
answers to "did this policy pass?" when nobody has stated an expectation yet, or when the
expectation is behavioural and no mechanism can be replayed. Collapsing either into `pass`
would manufacture a validation claim, which is the one thing this runner exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Outcome = Literal["pass", "fail", "pending", "skipped", "error"]

#: Outcomes that permit the build to proceed. `pending` and `skipped` are not passes --
#: they block the attestation -- but they are not defects in the policy either.
NON_BLOCKING: frozenset[str] = frozenset({"pass", "pending", "skipped"})


@dataclass(frozen=True)
class Case:
    """One eval case, as authored or as derived from a gate declaration."""

    id: str
    category: str
    prompt: str
    expect: str
    policy_id: str
    status: str = "ready"
    provenance: str = "authored"
    #: Executable form. Absent for prose-only cases, which are agent-mode material.
    execute: dict[str, Any] | None = None

    @property
    def runnable(self) -> bool:
        return self.status != "pending" and bool(self.execute)


@dataclass(frozen=True)
class CaseResult:
    case: Case
    outcome: Outcome
    #: How the verdict was reached: observed (a mechanism ran) or judged (a model assessed).
    #: Recorded per case so a reader can tell one from the other without inferring it.
    signal: str = "observed"
    detail: str = ""

    @property
    def blocking(self) -> bool:
        return self.outcome not in NON_BLOCKING


@dataclass
class PolicyResult:
    policy_id: str
    mode: str
    results: list[CaseResult] = field(default_factory=list)

    def count(self, outcome: Outcome) -> int:
        return sum(r.outcome == outcome for r in self.results)

    @property
    def blocking(self) -> bool:
        return any(r.blocking for r in self.results)

    @property
    def score(self) -> float | None:
        """Pass rate over cases that actually ran. None when nothing ran.

        Skipped and pending cases are excluded rather than counted as failures: a policy
        whose expectations are behavioural has not failed a deterministic run, it was
        never subject to one.
        """
        ran = self.count("pass") + self.count("fail") + self.count("error")
        return self.count("pass") / ran if ran else None

    @property
    def attestable(self) -> bool:
        """An attestation requires at least one passing *authored* case.

        Derived cases are generated from the same declaration the implementation reads, so
        they can show that declared behaviour is implemented but never that it is right.
        They gate the build; they are never allowed to stand in for a stated intent.
        """
        if self.blocking or self.count("pending"):
            return False
        return any(r.outcome == "pass" and r.case.provenance == "authored" for r in self.results)

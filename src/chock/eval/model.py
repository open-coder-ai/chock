"""Case and result types shared by the eval runner's modes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Outcome = Literal["pass", "fail", "pending", "skipped", "error"]

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
    execute: dict[str, Any] | None = None

    @property
    def runnable(self) -> bool:
        return self.status != "pending" and bool(self.execute)


@dataclass(frozen=True)
class CaseResult:
    case: Case
    outcome: Outcome
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
        """Pass rate over cases that actually ran. None when nothing ran."""
        ran = self.count("pass") + self.count("fail") + self.count("error")
        return self.count("pass") / ran if ran else None

    @property
    def attestable(self) -> bool:
        """An attestation requires at least one passing *authored* case."""
        if self.blocking or self.count("pending"):
            return False
        return any(r.outcome == "pass" and r.case.provenance == "authored" for r in self.results)

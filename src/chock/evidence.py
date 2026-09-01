"""chock's own evidence about chock's own wiring: witnessed live, and tested by our suite.

Upstream evidence grades the AGENT (agentseam's matrix rows and their bases). Nothing
upstream can carry what chock observed its own hooks doing in a real client, so those
records live here. `witnessed` (seen in a vendor's running client) and `tested` (an
automated fixture against our runtime) are kept apart and never collapsed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, NamedTuple

from agentseam import contract as _contract
from agentseam import matrix as _matrix

from chock.resources import package_data_dir

DATA_DIR = package_data_dir("chock", "data")
WITNESSES_PATH = DATA_DIR / "witnesses.json"
CLAIMS_PATH = DATA_DIR / "claims.json"

PLUGIN_HOOK = "plugin-hook"
WITNESS_SURFACES = ("pre-tool-use", "agent-hooks", PLUGIN_HOOK)

HONOURS_ASK = "honours_ask"
CLAIM_NAMES = (HONOURS_ASK,)

TESTED = "tested"
DOCUMENTED = "documented"
CLAIM_EVIDENCE = (TESTED, DOCUMENTED)

VERDICTS = (_contract.ALLOW, _contract.ASK, _contract.DENY)

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class EvidenceError(ValueError):
    """A ledger row that does not carry its own evidence; refused rather than half-read."""


class Witness(NamedTuple):
    """One live observation of chock's wiring in a vendor's real client."""

    agent: str
    surface: str
    client: str
    date: str
    method: str


class Claim(NamedTuple):
    """One claim chock's grading rests on, with the evidence that backs it."""

    agent: str
    claim: str
    verdict: str
    evidence: str
    test: str | None


def _text(row: dict[str, Any], field: str, where: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise EvidenceError(f"{where}: {field!r} is missing or empty in {row!r}")
    return value


def _one_of(value: str, allowed: tuple[str, ...], field: str, where: str) -> str:
    if value not in allowed:
        raise EvidenceError(f"{where}: {field}={value!r} is not one of {allowed}")
    return value


def _rows(source: Path | list[dict[str, Any]], where: str) -> list[dict[str, Any]]:
    data = json.loads(Path(source).read_text(encoding="utf-8")) if isinstance(source, Path) else source
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise EvidenceError(f"{where}: expected a list of rows")
    return data


def _no_duplicates(keys: list[tuple[str, ...]], where: str) -> None:
    seen: set[tuple[str, ...]] = set()
    for key in keys:
        if key in seen:
            raise EvidenceError(f"{where}: {key} recorded twice; one row per subject or the loser is invisible")
        seen.add(key)


def parse_witnesses(source: Path | list[dict[str, Any]] | None = None) -> tuple[Witness, ...]:
    """Read the witness ledger, refusing any row that does not state all five fields."""
    where = "witness ledger"
    rows = _rows(WITNESSES_PATH if source is None else source, where)
    witnesses = []
    for row in rows:
        agent = _one_of(_text(row, "agent", where), tuple(_matrix.agents()), "agent", where)
        surface = _one_of(_text(row, "surface", where), WITNESS_SURFACES, "surface", where)
        date = _text(row, "date", where)
        if not _DATE.match(date):
            raise EvidenceError(f"{where}: date={date!r} is not an ISO date; a witness without a day is a vibe")
        witnesses.append(Witness(agent, surface, _text(row, "client", where), date, _text(row, "method", where)))
    _no_duplicates([(w.agent, w.surface) for w in witnesses], where)
    return tuple(witnesses)


def parse_claims(source: Path | list[dict[str, Any]] | None = None) -> tuple[Claim, ...]:
    """Read the tested-claim table, refusing a `tested` claim that names no test."""
    where = "claim table"
    rows = _rows(CLAIMS_PATH if source is None else source, where)
    claims = []
    for row in rows:
        agent = _one_of(_text(row, "agent", where), tuple(_matrix.agents()), "agent", where)
        name = _one_of(_text(row, "claim", where), CLAIM_NAMES, "claim", where)
        verdict = _one_of(_text(row, "verdict", where), VERDICTS, "verdict", where)
        evidence = _one_of(_text(row, "evidence", where), CLAIM_EVIDENCE, "evidence", where)
        test = _text(row, "test", where) if evidence == TESTED else row.get("test")
        if evidence != TESTED and test is not None:
            raise EvidenceError(f"{where}: {agent} {name} names a test but is only {evidence!r}")
        claims.append(Claim(agent, name, verdict, evidence, test))
    _no_duplicates([(c.agent, c.claim) for c in claims], where)
    return tuple(claims)


def witnesses() -> tuple[Witness, ...]:
    """The shipped witness ledger."""
    return parse_witnesses()


def claims() -> tuple[Claim, ...]:
    """The shipped claim table."""
    return parse_claims()


def witness(agent: str, surface: str, *, ledger: tuple[Witness, ...] | None = None) -> Witness | None:
    """The ledger row for `agent` x `surface`, or None -- which means unwitnessed, not unknown."""
    rows = witnesses() if ledger is None else ledger
    return next((row for row in rows if row.agent == agent and row.surface == surface), None)


def claim(agent: str, name: str, *, table: tuple[Claim, ...] | None = None) -> Claim | None:
    """The claim row for `agent`, or None."""
    rows = claims() if table is None else table
    return next((row for row in rows if row.agent == agent and row.claim == name), None)


def honours_ask(agent: str, *, table: tuple[Claim, ...] | None = None) -> bool:
    """Whether a guard that cannot decide reaches a human on `agent`, per a TESTED claim."""
    row = claim(agent, HONOURS_ASK, table=table)
    return bool(row and row.evidence == TESTED and row.verdict == _contract.ASK)

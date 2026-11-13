"""The witness ledger: what it refuses to record, and the posture prose it gates."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from agentseam import matrix as _matrix

from chock import evidence
from chock.compile.surfaces import Surface
from chock.plugin import posture
from chock.plugin.codex import POSTURE_ENFORCED_CODEX
from chock.plugin.cursor import POSTURE_ENFORCED_CURSOR
from chock.plugin.devin import POSTURE_BESTEFFORT_DEVIN

WITNESS_ROW = {
    "agent": "cursor",
    "surface": "plugin-hook",
    "client": "Cursor",
    "date": "2026-08-24",
    "method": "live probe",
}

CLAIM_ROW = {
    "agent": "cursor",
    "claim": "honours_ask",
    "verdict": "ask",
    "honours": True,
    "evidence": "tested",
    "test": "tests/test_guard_fail_to_ask.py::test_a_crashed_guard_asks_rather_than_allowing",
}

RENDERS = {
    "codex_cli": (posture.enforced_codex, POSTURE_ENFORCED_CODEX),
    "cursor": (posture.enforced_cursor, POSTURE_ENFORCED_CURSOR),
    "devin": (posture.enforced_devin, POSTURE_BESTEFFORT_DEVIN),
}


def test_the_shipped_ledger_and_claim_table_load() -> None:
    """Loading is the validation, so the shipped data is checked by being read."""
    assert evidence.witnesses(), "an empty ledger would make every witness check vacuous"
    assert evidence.claims()


@pytest.mark.parametrize("field", sorted(WITNESS_ROW))
def test_a_witness_row_missing_any_field_is_refused(field: str) -> None:
    """A partial row is the failure mode the ledger exists to prevent: a claim with no record."""
    partial = {k: v for k, v in WITNESS_ROW.items() if k != field}

    with pytest.raises(evidence.EvidenceError) as excinfo:
        evidence.parse_witnesses([partial])

    assert field in str(excinfo.value)
    assert evidence.parse_witnesses([WITNESS_ROW]), "the unmutated row must still load"


@pytest.mark.parametrize("field", ("agent", "claim", "verdict", "honours", "evidence", "test"))
def test_a_claim_missing_its_evidence_is_refused(field: str) -> None:
    """Test (d): strip the basis off a claim and the loader refuses it, rather than grading on it."""
    stripped = {k: v for k, v in CLAIM_ROW.items() if k != field}

    with pytest.raises(evidence.EvidenceError):
        evidence.parse_claims([stripped])

    assert evidence.parse_claims([CLAIM_ROW])


def test_a_documented_only_claim_may_not_name_a_test_and_never_honours_ask() -> None:
    """`tested` and `documented` are the distinction; a documented claim earning a lift erases it."""
    documented = {**CLAIM_ROW, "evidence": "documented"}

    with pytest.raises(evidence.EvidenceError):
        evidence.parse_claims([documented])

    table = evidence.parse_claims([{k: v for k, v in documented.items() if k != "test"}])
    assert not evidence.honours_ask("cursor", table=table)
    assert evidence.honours_ask("cursor", table=evidence.parse_claims([CLAIM_ROW]))


def test_honours_derives_from_the_semantic_field_not_the_wire_word() -> None:
    """The mutation gate: equality with any verdict constant would fail one of these two rows."""
    assert evidence.honours_ask("cursor", table=evidence.parse_claims([CLAIM_ROW]))
    assert not evidence.honours_ask("cursor", table=evidence.parse_claims([{**CLAIM_ROW, "honours": False}]))


def test_a_canonical_outcome_word_is_not_a_wire_verdict() -> None:
    """agentseam's post-ACS vocabulary must not leak into a field that records what vendors said."""
    with pytest.raises(evidence.EvidenceError):
        evidence.parse_claims([{**CLAIM_ROW, "verdict": "escalate"}])


def test_an_unknown_agent_surface_or_date_is_refused() -> None:
    """Every closed vocabulary in a row is checked against its source, not merely non-empty."""
    for bad in (
        {**WITNESS_ROW, "agent": "no-such-vendor"},
        {**WITNESS_ROW, "surface": "carrier-pigeon"},
        {**WITNESS_ROW, "date": "last August"},
    ):
        with pytest.raises(evidence.EvidenceError):
            evidence.parse_witnesses([bad])


def test_two_rows_for_one_subject_are_refused() -> None:
    """A second row for the same subject would be silently unreachable behind the first."""
    with pytest.raises(evidence.EvidenceError):
        evidence.parse_witnesses([WITNESS_ROW, {**WITNESS_ROW, "client": "Cursor Nightly"}])


def test_the_in_agent_surfaces_the_ledger_accepts_are_the_compilers_own() -> None:
    """A surface renamed in the compiler must not leave the ledger accepting a dead token."""
    in_agent = {Surface.PRE_TOOL_USE.value, Surface.AGENT_HOOKS.value}
    assert in_agent < set(evidence.WITNESS_SURFACES)
    assert set(evidence.WITNESS_SURFACES) - in_agent == {evidence.PLUGIN_HOOK, evidence.GIT_HOOK_ENV, evidence.MANAGED}


@pytest.mark.parametrize("agent", sorted(RENDERS))
def test_a_witness_phrase_disappears_when_its_ledger_row_does(agent: str) -> None:
    """Test (b): the phrase is rendered FROM the row, so deleting the row must delete the phrase."""
    render, shipped = RENDERS[agent]
    ledger = evidence.witnesses()
    row = evidence.witness(agent, evidence.PLUGIN_HOOK, ledger=ledger)
    assert row is not None, f"{agent} claims a witness in its posture; the ledger must carry it"

    assert render(ledger=ledger) == shipped, "the packaged posture is not what the engine renders"
    assert f"witnessed blocking on {row.client}, {row.date}" in shipped

    without = render(ledger=tuple(w for w in ledger if w.agent != agent))
    assert "witnessed blocking" not in without, "the claim outlived its record"
    assert posture.UNWITNESSED in without


def test_a_vendor_the_matrix_says_cannot_block_gets_no_witness_phrase() -> None:
    """A ledger row is chock's evidence about its own wiring; it can never assert capability."""
    unable = next(a for a in _matrix.agents() if not _matrix.can_block(a, "pre_tool"))
    forged = (evidence.Witness(unable, evidence.PLUGIN_HOOK, "a real install", "2026-08-24", "live probe"),)

    assert posture.witness_clause(unable, ledger=forged) == posture.UNWITNESSED


@pytest.mark.parametrize("agent", sorted(RENDERS))
def test_a_rewrapped_posture_paragraph_still_passes(agent: str) -> None:
    """The legitimate edit: reflowing the prose must not fail a guard, or people route around it."""
    render, _ = RENDERS[agent]
    row = evidence.witness(agent, evidence.PLUGIN_HOOK)
    rewrapped = " ".join(render().split())

    assert f"witnessed blocking on {row.client}, {row.date}" in rewrapped


def test_every_tested_claim_names_a_test_that_actually_exercises_that_agent() -> None:
    """A fixture id nobody resolves is a documented claim wearing a tested one's clothes."""
    root = Path(__file__).resolve().parents[1]
    for claim in evidence.claims():
        assert claim.evidence == evidence.TESTED
        rel, _, name = claim.test.partition("::")
        assert (root / rel).exists(), f"{claim.agent}: {rel} does not exist"
        module = importlib.import_module(Path(rel).stem)
        assert hasattr(module, name), f"{claim.agent}: {rel} has no {name}"
        assert module.ASK_ON_THE_WIRE[claim.agent] == claim.verdict, (
            f"{claim.agent}: the test proves a different verdict than the claim records"
        )


def test_claude_codes_plugin_witness_cites_its_record_and_witnesses_no_repo_hook() -> None:
    """W-CC: the plugin route was witnessed, so only plugin-hook has a row; the repo-hook route was not."""
    row = evidence.witness("claude_code", evidence.PLUGIN_HOOK)
    assert row is not None
    assert "witness/results/witness-claude-code-2026-10-12.md" in row.method
    assert "198694b" in row.method
    assert evidence.witness("claude_code", Surface.PRE_TOOL_USE.value) is None


def test_devins_plugin_witness_cites_its_record_and_witnesses_no_repo_hook() -> None:
    """W-DEV: the plugin route was witnessed, so only plugin-hook has a row; the repo-hook route was not."""
    row = evidence.witness("devin", evidence.PLUGIN_HOOK)
    assert row is not None
    assert "witness/results/witness-devin-2026-10-08.md" in row.method
    assert "0f06113" in row.method
    assert evidence.witness("devin", Surface.PRE_TOOL_USE.value) is None


def test_copilots_plugin_witness_cites_its_record_and_names_what_it_did_not_cover() -> None:
    """WIT-1: keyed by agentseam's bundle-format id `copilot`, the key a plugin-hook lookup for that client uses."""
    row = evidence.witness("copilot", evidence.PLUGIN_HOOK)
    assert row is not None
    assert evidence.witness("vscode_copilot", evidence.PLUGIN_HOOK) is None
    assert evidence.witness("vscode_copilot", Surface.AGENT_HOOKS.value) is not None
    assert "witness/results/witness-copilot-2026-10-11.md" in row.method
    assert "83f636d" in row.method
    assert "Not covered: VS Code agent mode" in row.method
    assert "VS Code" not in row.client


def test_groks_plugin_witness_cites_its_record_and_claims_no_gate() -> None:
    """WIT-G: keyed `grok`, the agent chock's grok install client and a plugin-hook lookup use; guard only."""
    row = evidence.witness("grok", evidence.PLUGIN_HOOK)
    assert row is not None
    assert row.client == "Grok Build 1.0.62, Windows 11"
    assert "witness/results/witness-grok-2026-10-17.md" in row.method
    assert "f52c055" in row.method
    assert "Blocked by chock policy: block-no-verify" in row.method
    assert "--trust" in row.method and "no hook trust prompt" in row.method
    assert "no gate refusal is claimed" in row.method
    assert evidence.witness("grok", Surface.PRE_TOOL_USE.value) is None


def test_gooses_plugin_witness_cites_its_record_and_the_sh_it_needed() -> None:
    """WIT-GOOSE: keyed `goose`, the agent chock's goose install client and a plugin-hook lookup use; guard and gate."""
    row = evidence.witness("goose", evidence.PLUGIN_HOOK)
    assert row is not None
    assert row.client == "goose 1.55.0 CLI, Windows 11"
    assert "witness/results/witness-goose-2026-10-18.md" in row.method
    assert "6316fd3" in row.method
    assert "Blocked by chock policy: block-no-verify" in row.method
    assert "Unpinned GitHub Action detected" in row.method
    assert "sh on PATH" in row.method and "`sh -c`" in row.method
    assert evidence.witness("goose", Surface.PRE_TOOL_USE.value) is None


def test_antigravitys_plugin_witness_cites_its_record_and_the_turn_end_gate() -> None:
    """WIT-AGY: keyed `antigravity`, chock's antigravity install client's agent; guard refused, gate at turn end."""
    row = evidence.witness("antigravity", evidence.PLUGIN_HOOK)
    assert row is not None
    assert row.client == "Antigravity IDE (version not recorded), Windows 11"
    assert "witness/results/witness-antigravity-2026-10-18.md" in row.method
    assert "11121b3" in row.method
    assert "Blocked by chock policy: block-no-verify" in row.method
    assert "Stop hook blocked termination: Unpinned GitHub Action det" in row.method
    assert "It refused at turn end" in row.method and "did not refuse the write itself" in row.method
    assert "quote_free" in row.method and "Windows build only" in row.method
    assert evidence.witness("antigravity", Surface.PRE_TOOL_USE.value) is None


def test_the_shipped_ledger_is_the_file_on_disk() -> None:
    """The loader reads packaged data, so the check must be against that file, not a fixture."""
    rows = json.loads(evidence.WITNESSES_PATH.read_text(encoding="utf-8"))
    assert {(r["agent"], r["surface"]) for r in rows} == {(w.agent, w.surface) for w in evidence.witnesses()}

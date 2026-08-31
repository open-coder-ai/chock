"""The eval runner, pinned at the points where being wrong would be silent."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from chock.eval.cli import main, run_deterministic
from chock.eval.derive import derive_cases
from chock.eval.execute import run_case
from chock.eval.model import Case, CaseResult, PolicyResult
from chock.eval.suites import discover_policies

BASELINE = Path(__file__).resolve().parents[1] / ".agents" / "policies"


def _policy(repo: Path, policy_id: str):
    found = discover_policies(repo, policy_id)
    assert found, f"{policy_id} was not discovered under {repo}"
    return found[0]


def _repo_with(tmp_path: Path, policy_id: str) -> Path:
    target = tmp_path / ".agents" / "policies" / policy_id
    target.parent.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copytree(BASELINE / policy_id, target)
    return tmp_path


def test_a_placeholder_case_is_pending_not_a_pass(tmp_path: Path) -> None:
    """`new policy` scaffolds TODO cases. A TODO triggers nothing, so it would otherwise pass."""
    case = Case(id="tc-001", category="trigger", prompt="TODO", expect="TODO", policy_id="p", status="pending")
    result = run_case(case, tmp_path, tmp_path, [])
    assert result.outcome == "pending"


def test_a_prose_only_case_is_skipped_not_a_pass(tmp_path: Path) -> None:
    case = Case(id="tc-001", category="behavior", prompt="the agent refuses", expect="refusal", policy_id="p")
    result = run_case(case, tmp_path, tmp_path, [])
    assert result.outcome == "skipped"


def test_a_guard_that_cannot_run_is_an_error_not_a_block(tmp_path: Path) -> None:
    """Reading "could not launch" as "blocked" made every allow-case fail under WSL bash."""
    case = Case(
        id="tc-001",
        category="trigger",
        prompt="x",
        expect="x",
        policy_id="p",
        execute={"command": "rm -rf /", "expect": "block"},
    )
    missing = tmp_path / "absent-guard.sh"
    result = run_case(case, tmp_path, tmp_path, [missing])
    assert result.outcome == "error", result.detail


def _passing(provenance: str) -> CaseResult:
    case = Case(id="c", category="trigger", prompt="p", expect="e", policy_id="p", provenance=provenance)
    return CaseResult(case, "pass")


def test_derived_passes_alone_never_earn_an_attestation() -> None:
    """Derived cases come from the declaration the implementation reads."""
    derived_only = PolicyResult("p", "deterministic", [_passing("derived")])
    assert not derived_only.attestable

    with_authored = PolicyResult("p", "deterministic", [_passing("derived"), _passing("authored")])
    assert with_authored.attestable


def test_a_pending_case_blocks_the_attestation() -> None:
    pending = Case(id="c2", category="trigger", prompt="TODO", expect="TODO", policy_id="p", status="pending")
    result = PolicyResult("p", "deterministic", [_passing("authored"), CaseResult(pending, "pending")])
    assert not result.attestable
    assert not result.blocking, "a placeholder is not a defect in the policy"


def test_every_declared_manifest_format_gets_a_derived_case() -> None:
    """The gate declared four formats and handled one; nothing noticed for three builds."""
    gate = {
        "kind": "dependency_allowlist",
        "on": ["commit"],
        "params": {
            "manifests": ["requirements.txt", "pyproject.toml", "package.json", "go.mod"],
            "allowlist_file": ".chock/dependency-allowlist.txt",
        },
    }
    ids = {c.id for c in derive_cases("p", gate)}
    for fmt in ("requirements.txt", "pyproject.toml", "package.json", "go.mod"):
        assert f"derived-dep-block-{fmt}" in ids
        assert f"derived-dep-allow-{fmt}" in ids, "a block-only derivation cannot catch over-blocking"


def test_content_regex_derives_nothing() -> None:
    """Producing a string matching an arbitrary regex is not mechanical."""
    gate = {"kind": "content_regex", "on": ["commit"], "params": {"content_pattern": "AKIA[0-9A-Z]{16}"}}
    assert derive_cases("p", gate) == []


@pytest.mark.parametrize("policy_id", ["protect-main-branch", "scan-secrets", "verify-dependency-exists"])
def test_a_shipped_gate_policy_passes_its_own_suite(tmp_path: Path, policy_id: str) -> None:
    repo = _repo_with(tmp_path, policy_id)
    result = run_deterministic(_policy(repo, policy_id), repo)
    assert not result.blocking, [(r.case.id, r.outcome, r.detail) for r in result.results if r.blocking]
    assert result.attestable, "a shipped gate policy should carry at least one passing authored case"


def test_a_failing_expectation_is_reported_as_a_failure(tmp_path: Path) -> None:
    """Guard the guard: a runner that cannot fail is not measuring anything."""
    repo = _repo_with(tmp_path, "protect-main-branch")
    inverted = Case(
        id="inverted",
        category="trigger",
        prompt="a commit on main",
        expect="wrongly stated as allowed",
        policy_id="protect-main-branch",
        execute={"branch": "main", "files": {"a.txt": "x\n"}, "event": "commit", "expect": "allow"},
    )
    policy = _policy(repo, "protect-main-branch")
    result = run_case(inverted, policy.dir, repo, [])
    assert result.outcome == "fail"


def test_json_output_records_provenance_and_signal(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """A reader must be able to tell derived from authored without inferring it."""
    repo = _repo_with(tmp_path, "protect-main-branch")
    assert main(["protect-main-branch", "--repo", str(repo), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    cases = payload[0]["cases"]
    assert {c["provenance"] for c in cases} == {"authored", "derived"}
    assert all(c["signal"] == "observed" for c in cases)


def test_agent_mode_refuses_rather_than_reporting_a_pass(capsys: pytest.CaptureFixture) -> None:
    assert main(["--mode", "agent"]) == 2
    assert "not implemented" in capsys.readouterr().err


def test_authored_execute_blocks_match_the_published_schema() -> None:
    """These suites are copied wholesale by adopters; an `execute` block the validator"""
    schema_path = Path(__file__).resolve().parents[1] / "src" / "chock" / "validation" / "schemas" / "eval.schema.json"
    allowed = set(
        json.loads(schema_path.read_text(encoding="utf-8"))["properties"]["suite"]["properties"]["cases"]["items"][
            "properties"
        ]["execute"]["properties"]
    )
    checked = 0
    for suite_file in sorted(BASELINE.glob("*/evals/suite.yaml")):
        suite = (yaml.safe_load(suite_file.read_text(encoding="utf-8")) or {}).get("suite")
        if suite is None:
            continue
        for case in suite["cases"]:
            extra = set(case.get("execute") or {}) - allowed
            assert not extra, f"{suite_file.parent.parent.name}/{case['id']} uses undeclared keys {sorted(extra)}"
        checked += 1
    assert checked >= 10, f"only {checked} suite(s) were checked"


def _compiled_gate(repo: Path, policy_id: str) -> Path:
    return repo / ".chock" / "compiled" / policy_id / "git-hook" / "gate.json"


def test_the_suite_replays_the_installed_gate_not_the_manifest(tmp_path: Path) -> None:
    """A weakened compiled gate must fail the suite that vouches for the policy."""
    from chock.eval.execute import resolve_gate
    from chock.scaffold.recompile import recompile

    repo = _repo_with(tmp_path, "scan-secrets")
    recompile(repo, ["claude"], skip_hooks=True)

    spec, source = resolve_gate(repo / ".agents" / "policies" / "scan-secrets", repo)
    assert source == "compiled", "a compiled policy must be judged on its compiled gate"

    gate = _compiled_gate(repo, "scan-secrets")
    weakened = json.loads(gate.read_text(encoding="utf-8"))
    weakened["params"]["content_pattern"] = "ZZZ_NEVER_MATCHES"
    gate.write_text(json.dumps(weakened), encoding="utf-8")

    spec, source = resolve_gate(repo / ".agents" / "policies" / "scan-secrets", repo)
    assert source == "compiled"
    assert spec["params"]["content_pattern"] == "ZZZ_NEVER_MATCHES", "the tampered gate must be what runs"


def test_an_uncompiled_policy_falls_back_to_its_manifest(tmp_path: Path) -> None:
    """`chock new` writes a policy and its suite before anything is compiled."""
    from chock.eval.execute import resolve_gate

    repo = _repo_with(tmp_path, "scan-secrets")
    assert not _compiled_gate(repo, "scan-secrets").exists()

    spec, source = resolve_gate(repo / ".agents" / "policies" / "scan-secrets", repo)
    assert source == "manifest"
    assert spec is not None and spec["kind"] == "content_regex"


def test_an_unreadable_compiled_gate_errors_rather_than_using_the_manifest(tmp_path: Path) -> None:
    """Falling back here would convert a broken installed control into a passing suite."""
    from chock.eval.execute import resolve_gate
    from chock.scaffold.recompile import recompile

    repo = _repo_with(tmp_path, "scan-secrets")
    recompile(repo, ["claude"], skip_hooks=True)
    _compiled_gate(repo, "scan-secrets").write_text("{ not json", encoding="utf-8")

    spec, source = resolve_gate(repo / ".agents" / "policies" / "scan-secrets", repo)
    assert spec is None and source == "unreadable"

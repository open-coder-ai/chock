"""Coverage/compliance honesty regressions from the 2026-08 full-repo audit (P0-C).

For a governance tool the worst bug is an overclaim: coverage says enforced when nothing
enforces. These pin the specific overclaims the audit found.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml
from conftest import baseline_policy

from chock.authoring import compliance
from chock.compile.compiler import compile_policy
from chock.compile.surfaces import Surface


def _policy_with_events(tmp_path: Path, events: list[str]) -> Path:
    """A copy of protect-main-branch whose hook.gate fires on `events`."""
    dest = tmp_path / "protect-main-branch"
    shutil.copytree(baseline_policy("protect-main-branch"), dest)
    mf = dest / "manifest.yaml"
    data = yaml.safe_load(mf.read_text(encoding="utf-8"))
    data["hook"]["gate"]["on"] = events
    mf.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return dest


# ---- C1: a gate with no commit/push event must not report enforced-at-commit ----
def test_tool_use_only_gate_is_not_enforced_at_commit(tmp_path: Path) -> None:
    policy = _policy_with_events(tmp_path, ["tool_use"])
    out = tmp_path / ".chock" / "compiled"
    result = compile_policy(policy, targets=[Surface.GIT_HOOK.value], output_root=out, agents=["claude"])
    # no shim, no gate.json counted -> git-hook is not an emitted surface
    assert result.artifacts.get("git-hook", []) == []
    assert result.coverage["protect-main-branch"]["claude"] != "enforced-at-commit"


def test_commit_gate_still_enforced_at_commit(tmp_path: Path) -> None:
    policy = _policy_with_events(tmp_path, ["commit", "push"])
    out = tmp_path / ".chock" / "compiled"
    result = compile_policy(policy, targets=[Surface.GIT_HOOK.value], output_root=out, agents=["claude"])
    assert result.artifacts["git-hook"]  # shims emitted
    assert result.coverage["protect-main-branch"]["claude"] == "enforced-at-commit"


# ---- C2 (managed): branch protection emits no static deny; emitted patterns are real regexes ----
def test_managed_patterns_are_honest_and_valid(tmp_path: Path) -> None:
    import re

    # protect-main-branch enforces by resolving the current branch, which a static managed
    # setting cannot do -- so its managed deny is deliberately EMPTY, not a branch-blind
    # command-text approximation that misses `git commit` on main and false-positives on
    # "main" in a message.
    pmb = tmp_path / ".chock" / "compiled"
    compile_policy(
        baseline_policy("protect-main-branch"),
        targets=[Surface.MANAGED_SETTING.value],
        output_root=pmb,
        agents=["claude"],
    )
    pmb_managed = json.loads(
        (pmb / "protect-main-branch" / "managed-setting" / "managed-settings.json").read_text()
    )
    assert pmb_managed["deny"] == [], "branch protection cannot be a static managed deny; must be empty"

    # scan-secrets does emit credential patterns; each must be a valid regex carrying no raw
    # U+0008 backspace byte (the original \\b-vs-backspace regression).
    ss = tmp_path / ".chock-ss" / "compiled"
    compile_policy(
        baseline_policy("scan-secrets"),
        targets=[Surface.MANAGED_SETTING.value],
        output_root=ss,
        agents=["claude"],
    )
    ss_managed = json.loads(
        (ss / "scan-secrets" / "managed-setting" / "managed-settings.json").read_text()
    )
    assert ss_managed["deny"], "scan-secrets must emit managed deny patterns"
    for entry in ss_managed["deny"]:
        pattern = entry["pattern"]
        assert "\b" not in pattern, "must not carry a U+0008 backspace byte"
        re.compile(pattern)  # must be a valid regex


# ---- auto_compile residual: a drop-in uses the repo's configured agents, not all 13 ----
def test_auto_compile_uses_configured_agents(tmp_path: Path) -> None:
    from chock.hooks.autocompile import auto_compile

    (tmp_path / ".chock").mkdir()
    (tmp_path / ".chock" / "config.yaml").write_text("chock:\n  supported_agents: [claude, gemini]\n", encoding="utf-8")
    pol = tmp_path / ".agents" / "policies" / "protect-main-branch"
    shutil.copytree(baseline_policy("protect-main-branch"), pol)
    auto_compile(tmp_path)
    coverage = json.loads((tmp_path / ".chock" / "coverage.json").read_text(encoding="utf-8"))
    assert set(coverage["protect-main-branch"]) == {"claude", "gemini"}, "must not credit all 13 agents"


# ---- C3: a claim whose compiled mechanism was deleted is not counted as covered ----
def test_compliance_drops_a_claim_whose_compiled_output_is_gone(tmp_path: Path) -> None:
    pol = tmp_path / ".agents" / "policies" / "block-destructive-commands"
    src = baseline_policy("block-destructive-commands")
    shutil.copytree(src, pol)
    compiled_root = tmp_path / ".chock" / "compiled"
    compile_policy(pol, output_root=compiled_root, agents=["claude"])

    control = None
    manifest = yaml.safe_load((pol / "manifest.yaml").read_text(encoding="utf-8"))
    for claim in (manifest.get("compliance") or {}).get("owasp_asi") or []:
        control = claim["control"] if isinstance(claim, dict) else claim
        break
    if control is None:
        return  # this baseline declares no owasp claim; nothing to assert

    # compiled and present -> covered/partial
    before = compliance._build_report(tmp_path, "owasp_asi")["owasp_asi"][control]["state"]
    assert before in ("covered", "partial")
    # delete the mechanism; the claim must no longer count
    shutil.rmtree(compiled_root / "block-destructive-commands")
    after = compliance._build_report(tmp_path, "owasp_asi")["owasp_asi"][control]["state"]
    assert after == "uncovered"


# ---- H1: compliance report fails closed on misuse instead of exiting 0 ----
def test_compliance_report_fails_closed_on_missing_repo(capsys) -> None:
    assert compliance.main(["report", "--repo", "/no/such/repo/here"]) == 2


def test_compliance_report_rejects_unknown_framework(tmp_path, capsys) -> None:
    assert compliance.main(["report", "--repo", str(tmp_path), "--framework", "owasp-asi"]) == 2


def test_compliance_rejects_unknown_subcommand(capsys) -> None:
    assert compliance.main(["repot"]) == 2

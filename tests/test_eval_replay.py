"""The eval runner resolves the guard strictly, and replays agent-event gates and git-event scripts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from conftest import baseline_policy

from chock.eval.cli import main
from chock.eval.execute import run_case
from chock.eval.model import Case
from chock.eval.suites import Policy, discover_policies
from chock.validation.checks_evals import _schema_validate_suite
from chock.validation.report import Report

POLICY_ID = "keep-marker"
SECRET = 'KEY = "' + "AKIA" + "IOSFODNN7EXAMPLE" + '"\n'
WAIVED = SECRET.rstrip("\n") + "  # chock: allow key\n"
_PRE_COMMIT = (
    "import subprocess, sys\n"
    "staged = subprocess.run(['git', 'diff', '--cached', '--name-only'], capture_output=True, text=True).stdout.split()\n"
    "for path in staged:\n"
    "    if 'ERASED' in open(path, encoding='utf-8').read():\n"
    "        print(f'{path}: the marker was erased', file=sys.stderr)\n"
    "        raise SystemExit(1)\n"
)
_COMMIT_MSG = (
    "import sys\n"
    "if 'WIP' in open(sys.argv[1], encoding='utf-8').read():\n"
    "    print('commit message says WIP', file=sys.stderr)\n"
    "    raise SystemExit(1)\n"
)
_PRE_PUSH = (
    "import sys\n"
    "if 'refs/heads/main' in sys.stdin.read():\n"
    "    print('no direct push to main', file=sys.stderr)\n"
    "    raise SystemExit(1)\n"
)


def _policy(repo: Path, *, gate_on: list[str] | None = None, files: dict[str, str] | None = None) -> Path:
    """A rule policy with an optional content gate and whatever implementations the case needs."""
    policy = repo / ".agents" / "policies" / POLICY_ID
    (policy / "implementations").mkdir(parents=True)
    manifest = yaml.safe_load((baseline_policy("protect-commit-privacy") / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["id"] = POLICY_ID
    manifest["enforcement"] = "block"
    events = [e for e in ("commit", "push", "commit-msg") if any(f.endswith(f"-{_seg(e)}.py") for f in files or {})]
    manifest["hook"] = {}
    if gate_on:
        manifest["hook"]["gate"] = {
            "kind": "content_regex",
            "on": gate_on,
            "action": "block",
            "message": "a key",
            "params": {"content_pattern": "AKIA[0-9A-Z]{16}", "allowlist_pragma": "chock:\\s*allow\\s+key"},
        }
    if events:
        manifest["hook"]["script"] = {"on": events}
    (policy / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    for name, text in (files or {}).items():
        (policy / "implementations" / name).write_text(text, encoding="utf-8")
    return policy


def _seg(event: str) -> str:
    return {"commit": "pre-commit", "push": "pre-push"}.get(event, event)


def _run(repo: Path, execute: dict, policy_dir: Path | None = None) -> tuple[str, str]:
    policy = discover_policies(repo, POLICY_ID)[0]
    case = Case("c1", "trigger", "p", "e", POLICY_ID, execute=execute)
    result = run_case(case, policy_dir or policy.dir, repo, policy.guards)
    return result.outcome, result.detail


# --- G3a: the guard is <id>.sh|.py, never "the first script in the directory" -----------------------


def test_a_helper_module_is_not_the_command_guard(tmp_path: Path) -> None:
    policy = _policy(tmp_path, files={"aaa_helper.py": "X = 1\n", f"{POLICY_ID}-gate.py": "pass\n"})
    assert Policy(POLICY_ID, policy, {}).guards == []


def test_the_guard_is_named_for_the_policy_even_when_others_sort_first(tmp_path: Path) -> None:
    policy = _policy(tmp_path, files={"aaa_helper.py": "X = 1\n", f"{POLICY_ID}.sh": "exit 0\n"})
    assert [g.name for g in Policy(POLICY_ID, policy, {}).guards] == [f"{POLICY_ID}.sh"]


def test_a_command_case_reaches_the_named_guard(tmp_path: Path) -> None:
    _policy(tmp_path, files={"aaa_helper.py": "raise SystemExit(0)\n", f"{POLICY_ID}.py": "raise SystemExit(1)\n"})
    outcome, detail = _run(tmp_path, {"command": "x", "expect": "block"})
    assert outcome == "error" and "without a reason" in detail  # ran the named guard, not the helper


def test_the_legacy_guard_names_still_resolve(tmp_path: Path) -> None:
    policy = tmp_path / "block-no-verify"
    (policy / "implementations").mkdir(parents=True)
    (policy / "implementations" / "block-no-verify.sh").write_text("exit 0\n", encoding="utf-8")
    assert [g.name for g in Policy("block-no-verify", policy, {}).guards] == ["block-no-verify.sh"]


# --- G3b: cases at the agent events ----------------------------------------------------------------


@pytest.mark.parametrize("event", ["tool_use", "pre-tool-use", "stop"])
def test_an_agent_event_case_replays_the_gate(tmp_path: Path, event: str) -> None:
    _policy(tmp_path, gate_on=["commit", "tool_use"])
    assert _run(tmp_path, {"event": event, "writes": {"app.py": SECRET}, "expect": "block"})[0] == "pass"
    assert _run(tmp_path, {"event": event, "writes": {"app.py": "x = 1\n"}, "expect": "allow"})[0] == "pass"


def test_an_agent_event_case_honours_head_files_for_a_waiver(tmp_path: Path) -> None:
    """The waiver counts only when HEAD already carries the line: the case can say which."""
    _policy(tmp_path, gate_on=["tool_use"])
    added = {"event": "tool_use", "writes": {"app.py": WAIVED}, "expect": "block"}
    assert _run(tmp_path, added)[0] == "pass"
    committed = {**added, "head_files": {"app.py": WAIVED}, "expect": "allow"}
    assert _run(tmp_path, committed)[0] == "pass"


def test_a_gate_not_declared_at_the_event_allows_and_the_case_says_so(tmp_path: Path) -> None:
    _policy(tmp_path, gate_on=["commit"])
    outcome, _ = _run(tmp_path, {"event": "tool_use", "writes": {"app.py": SECRET}, "expect": "block"})
    assert outcome == "fail"


def test_an_agent_event_case_without_writes_is_an_error_not_an_allow(tmp_path: Path) -> None:
    _policy(tmp_path, gate_on=["tool_use"])
    assert _run(tmp_path, {"event": "tool_use", "expect": "allow"})[0] == "error"


def test_commit_and_push_cases_are_unchanged(tmp_path: Path) -> None:
    _policy(tmp_path, gate_on=["commit"])
    assert _run(tmp_path, {"files": {"app.py": SECRET}, "expect": "block"})[0] == "pass"


# --- G3c: git-event scripts in a staged throwaway repo ---------------------------------------------


def test_a_pre_commit_script_case(tmp_path: Path) -> None:
    _policy(tmp_path, files={f"{POLICY_ID}-pre-commit.py": _PRE_COMMIT})
    base = {"event": "pre-commit", "head_files": {"page.txt": "MARKER\n"}}
    assert _run(tmp_path, {**base, "files": {"page.txt": "ERASED\n"}, "expect": "block"}) == (
        "pass",
        "page.txt: the marker was erased",
    )
    assert _run(tmp_path, {**base, "files": {"page.txt": "MARKER more\n"}, "expect": "allow"})[0] == "pass"


def test_a_commit_msg_script_case(tmp_path: Path) -> None:
    _policy(tmp_path, files={f"{POLICY_ID}-commit-msg.py": _COMMIT_MSG})
    assert _run(tmp_path, {"event": "commit-msg", "message": "WIP stuff\n", "expect": "block"})[0] == "pass"
    assert _run(tmp_path, {"event": "commit-msg", "message": "fix: a thing\n", "expect": "allow"})[0] == "pass"
    assert _run(tmp_path, {"event": "commit-msg", "expect": "allow"})[0] == "error"


def test_a_pre_push_script_case_reads_the_stdin_lines(tmp_path: Path) -> None:
    _policy(tmp_path, files={f"{POLICY_ID}-pre-push.py": _PRE_PUSH})
    line = "refs/heads/work {sha} refs/heads/{ref} {sha}".format(sha="0" * 40, ref="{ref}")
    blocked = {"event": "pre-push", "stdin": [line.format(ref="main")], "expect": "block"}
    allowed = {"event": "pre-push", "stdin": [line.format(ref="topic")], "expect": "allow"}
    assert _run(tmp_path, blocked)[0] == "pass"
    assert _run(tmp_path, allowed)[0] == "pass"


def test_a_script_event_the_policy_does_not_ship_is_an_error(tmp_path: Path) -> None:
    _policy(tmp_path, gate_on=["commit"])
    outcome, detail = _run(tmp_path, {"event": "pre-commit", "files": {"a": "b"}, "expect": "block"})
    assert outcome == "error" and "ships no script" in detail


def test_a_crashing_script_is_an_error_not_a_block(tmp_path: Path) -> None:
    _policy(tmp_path, files={f"{POLICY_ID}-pre-commit.py": "raise RuntimeError('boom')\n"})
    assert _run(tmp_path, {"event": "pre-commit", "files": {"a": "b"}, "expect": "block"})[0] == "error"


# --- the suite still validates, and the new forms count as executable, not tier 3 -------------------


def test_the_new_forms_validate_and_run_from_a_real_suite(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    policy = _policy(tmp_path, gate_on=["tool_use"], files={f"{POLICY_ID}-commit-msg.py": _COMMIT_MSG})
    cases = [
        {
            "id": "tc-001",
            "category": "trigger",
            "prompt": "an agent writes a key",
            "expect": "refused",
            "execute": {"event": "tool_use", "writes": {"app.py": SECRET}, "expect": "block"},
        },
        {
            "id": "tc-002",
            "category": "negative_trigger",
            "prompt": "an agent writes clean code",
            "expect": "allowed",
            "execute": {"event": "stop", "writes": {"app.py": "x = 1\n"}, "expect": "allow"},
        },
        {
            "id": "tc-003",
            "category": "behavior",
            "prompt": "a WIP message",
            "expect": "refused",
            "execute": {"event": "commit-msg", "message": "WIP\n", "expect": "block"},
        },
    ]
    suite = {"suite": {"id": "s", "policy_id": POLICY_ID, "metrics": {}, "cases": cases}}
    (policy / "evals").mkdir()
    (policy / "evals" / "suite.yaml").write_text(yaml.safe_dump(suite), encoding="utf-8")

    report = Report()
    _schema_validate_suite(policy / "evals" / "suite.yaml", report)
    assert not report.errors, [f.message for f in report.errors]

    assert main([POLICY_ID, "--repo", str(tmp_path), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert [c["outcome"] for c in doc[0]["cases"]] == ["pass", "pass", "pass"]

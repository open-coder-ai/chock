"""On a case-blind platform a protected path is protected however its case is typed, existing or not."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chock.gate import outside_repo, write_gate
from chock.gate.assemble import runner_source
from chock.gateway import gates as gateway_gates

PROTECTED = ".claude/settings.json"
CASED = ".CLAUDE/settings.json"
CONTENT = {"content_pattern": r"\{\}"}
FORBIDDEN = {"content_pattern": "(?!)", "forbidden_path_regex": r"^\.claude/settings\.json$"}


def _gate(root: Path, params: dict, scope: list[str] | None = None) -> Path:
    spec = {"kind": "content_regex", "on": ["commit", "tool_use"], "action": "block", "message": "matched"}
    spec = {**spec, "params": params, **({"paths": scope} if scope else {})}
    gate = root / ".chock" / "compiled" / "probe" / "pre-tool-use" / "gate.json"
    gate.parent.mkdir(parents=True)
    gate.write_text(json.dumps(spec), encoding="utf-8")
    runner = root / ".chock" / "bin" / "gate.py"
    runner.parent.mkdir(parents=True)
    runner.write_text(runner_source(), encoding="utf-8")
    return gate


def _write(path: str, root: Path):
    return SimpleNamespace(event="pre_tool", path=path, content="{}", raw={}, cwd=str(root))


def _verdict(gate: Path, path: str, root: Path, *, case_blind: bool | None):
    """ "deny" only when the gate itself matched; a runner that crashed is a different answer."""
    decision = write_gate.evaluate_gate(["--gate", str(gate)], _write(path, root), case_blind=case_blind)
    if decision is None:
        return None
    return "deny" if decision[0] == "deny" and "matched" in decision[1] else decision


@pytest.mark.parametrize("params", [{**CONTENT}, FORBIDDEN], ids=["scope glob", "forbidden path regex"])
def test_a_protected_path_that_does_not_exist_yet_is_denied_in_any_case(tmp_path, params):
    scope = [PROTECTED] if params is not FORBIDDEN else None
    gate = _gate(tmp_path, params, scope)
    assert not (tmp_path / ".claude").exists()

    assert _verdict(gate, PROTECTED, tmp_path, case_blind=True) == "deny"
    assert _verdict(gate, CASED, tmp_path, case_blind=True) == "deny"
    assert _verdict(gate, ".Claude/Settings.JSON", tmp_path, case_blind=True) == "deny"


@pytest.mark.parametrize("params", [{**CONTENT}, FORBIDDEN], ids=["scope glob", "forbidden path regex"])
def test_a_case_sensitive_platform_still_tells_the_cases_apart(tmp_path, params):
    scope = [PROTECTED] if params is not FORBIDDEN else None
    gate = _gate(tmp_path, params, scope)

    assert _verdict(gate, PROTECTED, tmp_path, case_blind=False) == "deny"
    assert _verdict(gate, CASED, tmp_path, case_blind=False) is None


def test_the_declared_outside_glob_matches_without_case_on_a_case_blind_platform():
    files = {"/Users/dev/.CLAUDE/memory/a.md": "x"}
    pattern = ["/users/dev/.claude/memory/*"]
    names = lambda path: (path,)  # noqa: E731 -- the name is already absolute here
    root = "/work/repo"

    assert outside_repo.judged_files(files, root, pattern, names, case_blind=True)
    assert not outside_repo.judged_files(files, root, pattern, names, case_blind=False)


def _gateway(params: dict, scope: list[str] | None = None) -> list[dict]:
    spec = {"kind": "content_regex", "params": params, "message": "blocked", "policy_id": "gw", "repo_root": "/r"}
    return [{**spec, **({"paths": scope} if scope else {})}]


@pytest.mark.parametrize(
    ("params", "scope"),
    [(CONTENT, [PROTECTED]), (FORBIDDEN, None)],
    ids=["scope glob", "forbidden path regex"],
)
def test_the_gateway_denies_a_protected_path_in_any_case_when_case_blind(params, scope):
    args = {"path": CASED, "content": "{}"}

    assert gateway_gates.evaluate(_gateway(params, scope), "write_file", args, case_blind=True) is not None
    assert gateway_gates.evaluate(_gateway(params, scope), "write_file", args, case_blind=False) is None
    assert gateway_gates.evaluate(_gateway(params, scope), "write_file", {**args, "path": PROTECTED}) is not None

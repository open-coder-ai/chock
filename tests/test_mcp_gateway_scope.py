"""The mcp-gateway judges a content_regex gate only inside its applies_to.paths bound."""

from __future__ import annotations

import json

from chock.compile.emitters import mcp_gateway as emitter
from chock.gateway import gates as gateway_gates


def _manifest(kind: str, params: dict) -> dict:
    return {
        "id": "gw-test",
        "hook": {"gate": {"kind": kind, "on": ["tool_use"], "action": "block", "message": "m", "params": params}},
    }


def _gate(kind: str, params: dict) -> dict:
    return {"kind": kind, "params": params, "message": "blocked", "policy_id": "gw-test"}


_PIN = {"content_pattern": r"uses:\s*\S+@v\d", "allowlist_pragma": "pragma: allow"}
_WORKFLOW_SCOPE = [".github/workflows/*", ".github/actions/*"]


def _scoped(params: dict | None = None) -> list[dict]:
    return [{**_gate("content_regex", params or _PIN), "paths": _WORKFLOW_SCOPE}]


def test_emitter_carries_applies_to_paths_into_the_gateway_spec(tmp_path):
    out = tmp_path / "mcp-gateway"
    out.mkdir()
    manifest = _manifest("content_regex", {"content_pattern": "x", "forbidden_path_regex": r"\.env$"})
    manifest["applies_to"] = {"paths": _WORKFLOW_SCOPE}
    emitter.emit(tmp_path, out, manifest)
    spec = json.loads((out / "gateway-gate.json").read_text(encoding="utf-8"))
    assert spec["paths"] == _WORKFLOW_SCOPE
    assert spec["params"]["forbidden_path_regex"] == r"\.env$"


def test_emitter_omits_paths_for_an_unbounded_gate(tmp_path):
    out = tmp_path / "mcp-gateway"
    out.mkdir()
    emitter.emit(tmp_path, out, _manifest("content_regex", {"content_pattern": "x"}))
    assert "paths" not in json.loads((out / "gateway-gate.json").read_text(encoding="utf-8"))


def test_bounded_gate_blocks_content_at_an_in_scope_path():
    args = {"path": ".github/workflows/ci.yml", "content": "- uses: a/b@v4"}
    assert gateway_gates.evaluate(_scoped(), "write_file", args) is not None


def test_bounded_gate_passes_content_at_an_out_of_scope_path():
    args = {"path": "README.md", "content": "- uses: a/b@v4"}
    assert gateway_gates.evaluate(_scoped(), "write_file", args) is None


def test_bounded_gate_does_not_judge_a_pathless_call():
    assert gateway_gates.evaluate(_scoped(), "create_note", {"text": "uses: a/b@v4"}) is None


def test_unbounded_gate_still_blocks_pathless_content():
    gates = [_gate("content_regex", _PIN)]
    assert gateway_gates.evaluate(gates, "create_note", {"text": "uses: a/b@v4"}) is not None


def test_path_is_recognised_under_other_keys_and_absolute_form():
    gate = {**_scoped()[0], "repo_root": "/work/repo"}
    hit = {"file_path": "/work/repo/.github/actions/x/action.yml", "content": "uses: a/b@v4"}
    assert gateway_gates.evaluate([gate], "edit", hit) is not None
    assert gateway_gates.evaluate([gate], "edit", {"filePath": "./.github/workflows/a.yml", "c": "uses: a/b@v4"})
    assert gateway_gates.evaluate([gate], "edit", {"path": "docs/a.md", "content": "uses: a/b@v4"}) is None


def test_forbidden_path_regex_blocks_a_matching_path_without_content():
    gates = [_gate("content_regex", {"content_pattern": "NOPE", "forbidden_path_regex": r"\.env$"})]
    assert gateway_gates.evaluate(gates, "write_file", {"path": "app/.env", "content": "a=b"}) is not None
    assert gateway_gates.evaluate(gates, "write_file", {"path": "app/main.py", "content": "a=b"}) is None


def test_forbidden_path_regex_is_bounded_by_scope():
    gate = {
        **_gate("content_regex", {"content_pattern": "NOPE", "forbidden_path_regex": r"\.env$"}),
        "paths": ["src/*"],
    }
    assert gateway_gates.evaluate([gate], "write_file", {"path": "app/.env", "content": "x"}) is None
    assert gateway_gates.evaluate([gate], "write_file", {"path": "src/.env", "content": "x"}) is not None


def test_pragma_on_the_line_does_not_waive_at_the_gateway_even_when_in_scope():
    args = {"path": ".github/workflows/ci.yml", "content": "uses: a/b@v4  # pragma: allow"}
    assert gateway_gates.evaluate(_scoped(), "write_file", args) is not None

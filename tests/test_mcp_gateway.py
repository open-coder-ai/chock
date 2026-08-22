"""mcp-gateway surface (chock#32 P3b): emitter, gate evaluation, proxy, honesty.

The load-bearing assertions: RUNTIME_KINDS stays in lockstep between the emitter and
the evaluator table (an emitted-but-unevaluable kind fails closed AND fails here), and
coverage_level never credits the surface until a P3c witness exists.
"""

from __future__ import annotations

import json

from chock.compile.emitters import mcp_gateway as emitter
from chock.compile.surfaces import Surface, coverage_level
from chock.gateway import gates as gateway_gates
from chock.gateway.proxy import Gateway
from chock.validation.checks_gate_shape import _validate_gate
from chock.validation.report import Report


def _manifest(kind: str, params: dict, message: str = "Blocked by test gate.") -> dict:
    return {
        "id": "gw-test",
        "hook": {"gate": {"kind": kind, "on": ["tool_use"], "action": "block", "message": message, "params": params}},
    }


# --- lockstep: emitter kinds == evaluator kinds


def test_emitter_and_evaluator_kinds_are_in_lockstep():
    assert tuple(sorted(emitter.RUNTIME_KINDS)) == gateway_gates.RUNTIME_KINDS


# --- shape validation


def test_egress_allowlist_params_validated():
    report = Report()
    _validate_gate(
        {"kind": "egress_allowlist", "on": ["tool_use"], "action": "block", "message": "m", "params": {}},
        "gate",
        report,
        tool_use_allowed=True,
    )
    assert any("allowed_hosts" in f.message for f in report.errors)


def test_egress_allowlist_rejects_commit_events():
    report = Report()
    _validate_gate(
        {
            "kind": "egress_allowlist",
            "on": ["commit"],
            "action": "block",
            "message": "m",
            "params": {"allowed_hosts": ["example.com"]},
        },
        "gate",
        report,
        tool_use_allowed=True,
    )
    assert any("tool_use" in f.message for f in report.errors)


# --- emitter


def test_emitter_writes_gateway_gate_for_runtime_kinds(tmp_path):
    out = tmp_path / "mcp-gateway"
    out.mkdir()
    emitted = emitter.emit(tmp_path, out, _manifest("egress_allowlist", {"allowed_hosts": ["api.example.com"]}))
    assert emitted, "egress gate must emit"
    spec = json.loads((out / "gateway-gate.json").read_text(encoding="utf-8"))
    assert spec["kind"] == "egress_allowlist"
    assert spec["binds"] == "url-arguments"


def test_emitter_skips_kinds_without_gateway_runtime(tmp_path):
    out = tmp_path / "mcp-gateway"
    out.mkdir()
    assert emitter.emit(tmp_path, out, _manifest("forbidden_ref", {"refs": ["main"]})) == []
    assert (
        emitter.emit(
            tmp_path, out, _manifest("dependency_allowlist", {"manifests": ["package.json"], "allowlist_file": "x"})
        )
        == []
    )


# --- coverage honesty: emitted, never credited


def test_mcp_gateway_surface_is_never_credited():
    for agent in ("claude", "cursor", "copilot", "gemini", "vscode"):
        level = coverage_level({Surface.MCP_GATEWAY}, agent, pre_tool_use_installed=False, ci_gate_installed=False)
        assert level == "unsupported", f"{agent} credited mcp-gateway before a P3c witness exists"


# --- gate evaluation


def _gate(kind: str, params: dict, message: str = "blocked") -> dict:
    return {"kind": kind, "params": params, "message": message, "policy_id": "gw-test"}


_FAKE_AWS_KEY = "AKIAIOSFODNN7EXAMPLE"  # pragma: allowlist secret


def test_content_regex_blocks_string_argument_and_names_policy():
    gates = [_gate("content_regex", {"content_pattern": r"AKIA[A-Z0-9]{16}"})]
    msg = gateway_gates.evaluate(gates, "write_file", {"content": f"key = {_FAKE_AWS_KEY}"})
    assert msg and "[gw-test]" in msg


def test_content_regex_ignores_allowlist_pragma_at_the_gateway():
    # The scanned text is the live, attacker-controlled tool-call argument; honoring a
    # same-line pragma would let one appended comment defeat the scan (review finding #6).
    gates = [_gate("content_regex", {"content_pattern": "SECRET", "allowlist_pragma": "pragma: allow"})]
    assert gateway_gates.evaluate(gates, "write_file", {"content": "SECRET  # pragma: allow"}) is not None


def test_content_regex_empty_pattern_fails_closed():
    gates = [_gate("content_regex", {"content_pattern": ""})]
    assert gateway_gates.evaluate(gates, "write_file", {"content": "anything"}) is not None


def test_batch_request_is_screened_element_by_element():

    gw = Gateway.__new__(Gateway)
    gw.gates = [_gate("egress_allowlist", {"allowed_hosts": ["example.com"]})]
    batch = [
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "fetch", "arguments": {"url": "https://evil.io/x"}},
        }
    ]
    blocked = gw._screen(batch)
    assert blocked is not None and blocked[0] == 3


def test_non_object_params_are_refused_not_crashed():

    gw = Gateway.__new__(Gateway)
    gw.gates = []
    for bad in ([1], "x", 5, True):
        blocked = gw._screen({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": bad})
        assert blocked is not None and "params is not an object" in blocked[1]


def test_egress_blocks_unlisted_host_allows_listed_and_subdomains():
    gates = [_gate("egress_allowlist", {"allowed_hosts": ["example.com"]})]
    assert gateway_gates.evaluate(gates, "fetch", {"url": "https://evil.io/x"}) is not None
    assert gateway_gates.evaluate(gates, "fetch", {"url": "https://example.com/ok"}) is None
    assert gateway_gates.evaluate(gates, "fetch", {"url": "https://api.example.com/ok"}) is None
    assert gateway_gates.evaluate(gates, "fetch", {"url": "https://notexample.com/x"}) is not None


def test_egress_catches_non_http_schemes_and_scheme_relative():
    gates = [_gate("egress_allowlist", {"allowed_hosts": ["example.com"]})]
    for url in (
        "wss://evil.io/x",
        "ws://evil.io",
        "ftp://evil.io/x",
        "file:///etc/passwd",
        "gopher://evil.io/x",
        "//evil.io/x",
    ):
        assert gateway_gates.evaluate(gates, "fetch", {"url": url}) is not None, url


def test_egress_catches_second_host_embedded_in_query():
    gates = [_gate("egress_allowlist", {"allowed_hosts": ["example.com"]})]
    assert gateway_gates.evaluate(gates, "fetch", {"url": "http://example.com/a?next=http://evil.io/b"}) is not None


def test_egress_catches_percent_encoded_host():
    gates = [_gate("egress_allowlist", {"allowed_hosts": ["example.com"]})]
    assert gateway_gates.evaluate(gates, "fetch", {"u": "redirect=http%3A%2F%2Fevil.io%2Fx"}) is not None


def test_unknown_gate_kind_fails_closed():
    msg = gateway_gates.evaluate([_gate("future_kind", {})], "any", {})
    assert msg and "fail closed" in msg


def test_unreadable_gate_file_fails_closed(tmp_path):
    d = tmp_path / ".chock" / "compiled" / "broken" / "mcp-gateway"
    d.mkdir(parents=True)
    (d / "gateway-gate.json").write_text("{not json", encoding="utf-8")
    gates = gateway_gates.load_gates(tmp_path)
    assert gateway_gates.evaluate(gates, "any", {}) is not None

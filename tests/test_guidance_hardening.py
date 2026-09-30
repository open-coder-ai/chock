"""Whatever the repo holds, `chock mcp` answers every request and keeps serving; its claims hold on the wire."""

from __future__ import annotations

import json
import os

import pytest
from guidance_fixture import contract, install
from test_guidance_server import call, rpc, run

from chock.guidance import advise
from chock.guidance.server import Server

J = "src/main/java/app/"
PLAN = "add a file download endpoint"


def _config(root, text: str) -> None:
    (root / ".chock").mkdir(exist_ok=True)
    (root / ".chock" / "config.yaml").write_text(text, encoding="utf-8")


def _answers_then_pings(root) -> dict:
    """One tool call followed by a ping: the call is answered and the server is still alive for the ping."""
    replies = run(root, call(1, plan=PLAN, paths=[J + "F.java"]), rpc(2, "ping"))
    assert [r["id"] for r in replies] == [1, 2]
    return replies[0]


@pytest.mark.parametrize(
    ("write", "expect"),
    [
        (lambda r: install(r, "[" * 100_000), "selection is not valid JSON"),
        (lambda r: _config(install(r), "a: [\n"), "config.yaml cannot be read"),
        (lambda r: _config(install(r), "[" * 100_000 + "\n"), "nests deeper than 64 levels"),
        (lambda r: _config(install(r), "".join(" " * (2 * i) + f"k{i}:\n" for i in range(200))), "nests deeper"),
    ],
)
def test_a_broken_repo_file_is_a_tool_error_and_the_server_carries_on(tmp_path, write, expect):
    write(tmp_path)
    reply = _answers_then_pings(tmp_path)
    assert reply["result"]["isError"] is True
    assert expect in reply["result"]["structuredContent"]["errors"][0]
    assert reply["result"]["structuredContent"]["guidance"] == []


def test_a_contract_rule_with_a_mistyped_cwe_is_an_error(tmp_path):
    install(tmp_path)
    doc = contract()
    doc["rules"][0]["cwe"] = 5
    (tmp_path / ".agents/policies/java-security/skills/java-security/references/setup-contract.json").write_text(
        json.dumps(doc), encoding="utf-8"
    )
    reply = _answers_then_pings(tmp_path)
    assert "cwe that is not a list" in reply["result"]["structuredContent"]["errors"][0]


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_a_symlinked_config_is_refused_not_followed(tmp_path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere") / "config.yaml"
    outside.write_text("policies:\n  disabled: [java-security]\n", encoding="utf-8")
    install(tmp_path)
    (tmp_path / ".chock").mkdir()
    (tmp_path / ".chock" / "config.yaml").symlink_to(outside)
    reply = _answers_then_pings(tmp_path)
    assert "symlink" in reply["result"]["structuredContent"]["errors"][0]


def test_an_ordinary_config_still_leaves_the_policy_on(tmp_path):
    _config(install(tmp_path), "policies:\n  disabled: []\n")
    reply = _answers_then_pings(tmp_path)
    assert reply["result"]["isError"] is False and reply["result"]["structuredContent"]["guidance"]


def test_an_unexpected_failure_is_an_internal_error_not_a_dead_server(tmp_path, monkeypatch):
    def boom(*_args):
        raise ZeroDivisionError

    monkeypatch.setattr(advise, "guidance", boom)
    server = Server(install(tmp_path))
    reply = server.handle(json.loads(call(1, plan=PLAN, paths=[])))
    assert reply["error"]["code"] == -32603 and reply["id"] == 1
    assert server.handle(json.loads(rpc(2, "ping")))["result"] == {}


def test_the_whole_response_line_fits_the_byte_budget(tmp_path):
    root = install(tmp_path)
    plan = " ".join(word for rule in contract()["rules"] for word in rule["id"].split("-"))[:4000]
    stdin = (call(1, plan=plan, paths=[]) + "\n").encode()
    import subprocess
    import sys

    proc = subprocess.run([sys.executable, "-m", "chock", "mcp", "--repo", str(root)], input=stdin, capture_output=True)
    (line,) = proc.stdout.splitlines()
    payload = json.loads(line)["result"]["structuredContent"]
    assert payload["guidance"], "the broad plan must return rules for the budget to matter"
    assert len(line) <= advise.data()["limits"]["response_bytes"]
    assert len(line) <= advise.wire_bytes(payload)


def test_the_line_cap_counts_bytes_not_characters(tmp_path):
    over = b'{"jsonrpc":"2.0","id":1,"method":"ping","params":"' + "é".encode() * 600_000 + b'"}\n'
    replies = run(install(tmp_path), raw=over + rpc(2, "ping").encode() + b"\n")
    assert replies[0]["error"]["message"] == "request line too large"
    assert replies[-1]["id"] == 2


@pytest.mark.parametrize("bad_id", [{"a": 1}, [1], 1.5, True])
def test_an_id_that_is_not_a_string_or_integer_is_refused(tmp_path, bad_id):
    (reply,) = run(install(tmp_path), json.dumps({"jsonrpc": "2.0", "id": bad_id, "method": "ping"}))
    assert reply["error"]["code"] == -32600 and reply["id"] is None


def test_string_and_integer_ids_are_echoed(tmp_path):
    replies = run(install(tmp_path), rpc("a", "ping"), rpc(7, "ping"))
    assert [r["id"] for r in replies] == ["a", 7]


def test_paths_is_required(tmp_path):
    reply = Server(install(tmp_path)).handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "chock_guidance", "arguments": {"plan": PLAN}},
        }
    )
    assert reply["result"]["isError"] is True


def test_an_absent_selection_says_the_user_level_file_is_not_read(tmp_path):
    reply = _answers_then_pings(install(tmp_path))
    assert "not read" in reply["result"]["structuredContent"]["selection"]["java-security"]


def test_the_tool_claims_guidance_for_java_only_and_names_every_file_it_reads(tmp_path):
    (reply,) = run(install(tmp_path), rpc(1, "tools/list"))
    description = reply["result"]["tools"][0]["description"]
    assert "agent code" not in description and "not enforcement" in description
    assert ".chock/config.yaml" in description

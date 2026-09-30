"""`chock mcp` over real stdio: initialize, tools/list, tools/call, malformed JSON, unknown method."""

from __future__ import annotations

import json
import subprocess
import sys

from guidance_fixture import install

J = "src/main/java/app/"


def run(root, *lines: str, raw: bytes | None = None) -> list[dict]:
    """Feed lines to a fresh `chock mcp` process; every JSON line it answered, in order."""
    stdin = raw if raw is not None else ("\n".join(lines) + "\n").encode()
    proc = subprocess.run(
        [sys.executable, "-m", "chock", "mcp", "--repo", str(root)], input=stdin, capture_output=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr.decode()
    return [json.loads(line) for line in proc.stdout.decode().splitlines()]


def rpc(id_, method, params=None) -> str:
    message = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        message["params"] = params
    return json.dumps(message)


def call(id_, **arguments) -> str:
    return rpc(id_, "tools/call", {"name": "chock_guidance", "arguments": arguments})


def test_initialize_negotiates_and_declares_only_tools(tmp_path):
    (reply,) = run(install(tmp_path), rpc(1, "initialize", {"protocolVersion": "2025-06-18"}))
    assert reply["id"] == 1
    assert reply["result"]["protocolVersion"] == "2025-06-18"
    assert reply["result"]["capabilities"] == {"tools": {}}
    assert reply["result"]["serverInfo"]["name"] == "chock"


def test_initialize_with_an_unknown_version_answers_with_one_it_speaks(tmp_path):
    (reply,) = run(install(tmp_path), rpc(1, "initialize", {"protocolVersion": "1999-01-01"}))
    assert reply["result"]["protocolVersion"] == "2025-06-18"


def test_tools_list_is_one_read_only_tool(tmp_path):
    (reply,) = run(install(tmp_path), rpc(2, "tools/list"))
    (tool,) = reply["result"]["tools"]
    assert tool["name"] == "chock_guidance"
    assert tool["annotations"]["readOnlyHint"] is True
    assert tool["annotations"]["destructiveHint"] is False
    assert tool["annotations"]["openWorldHint"] is False
    assert tool["inputSchema"]["required"] == ["plan", "paths"]
    assert tool["inputSchema"]["properties"]["plan"]["maxLength"] == 4000


def test_tools_call_returns_the_path_traversal_rule(tmp_path):
    (reply,) = run(install(tmp_path), call(3, plan="add a file download endpoint", paths=[J + "FilesController.java"]))
    result = reply["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload == result["structuredContent"]
    first = payload["guidance"][0]
    assert (first["id"], first["verdict"]) == ("java-path-traversal-request-data", "deny")
    assert "getFileName" in first["constraint"]


def test_notifications_get_no_response_and_ids_are_echoed(tmp_path):
    notification = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
    replies = run(install(tmp_path), notification, rpc("abc", "ping"))
    assert [r["id"] for r in replies] == ["abc"]
    assert replies[0]["result"] == {}


def test_malformed_json_is_a_parse_error_and_the_server_carries_on(tmp_path):
    replies = run(install(tmp_path), "{not json", rpc(4, "ping"))
    assert replies[0]["error"]["code"] == -32700
    assert replies[0]["id"] is None
    assert replies[1]["result"] == {}


def test_unknown_method_is_method_not_found(tmp_path):
    (reply,) = run(install(tmp_path), rpc(5, "resources/list"))
    assert reply["error"]["code"] == -32601
    assert reply["id"] == 5


def test_unknown_tool_is_invalid_params(tmp_path):
    (reply,) = run(install(tmp_path), rpc(6, "tools/call", {"name": "chock_write", "arguments": {}}))
    assert reply["error"]["code"] == -32602


def test_non_request_payloads_are_invalid_requests(tmp_path):
    replies = run(install(tmp_path), "[1, 2]", '"text"', '{"method": "ping", "id": 7}')
    assert [r["error"]["code"] for r in replies] == [-32600, -32600, -32600]


def test_bad_arguments_are_a_tool_error_not_a_crash(tmp_path):
    replies = run(install(tmp_path), call(8, plan="x", paths="src", extra=1), call(9, plan=5, paths=[]))
    assert [r["result"]["isError"] for r in replies] == [True, True]


def test_an_oversize_line_is_refused_and_the_next_request_still_answers(tmp_path):
    big = b'{"jsonrpc":"2.0","id":1,"method":"ping","params":"' + b"x" * (1 << 20) + b'"}\n'
    replies = run(install(tmp_path), raw=big + rpc(2, "ping").encode() + b"\n")
    assert replies[0]["error"]["code"] == -32600
    assert replies[-1]["id"] == 2


def test_no_policies_dir_refuses_to_start(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "chock", "mcp", "--repo", str(tmp_path)], capture_output=True, input=b"", timeout=60
    )
    assert proc.returncode == 2
    assert b".agents/policies" in proc.stderr

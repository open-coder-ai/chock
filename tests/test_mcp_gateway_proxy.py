"""mcp-gateway proxy + CLI (chock#32 P3b): stdio interception, batch screening,"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import textwrap
from pathlib import Path

from chock.compile.emitters import mcp_gateway as emitter
from chock.gateway.proxy import Gateway

_FAKE_AWS_KEY = "AKIAIOSFODNN7EXAMPLE"  # pragma: allowlist secret


_ECHO_SERVER = textwrap.dedent(
    """
    import json, sys
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        print(json.dumps({"jsonrpc": "2.0", "id": req.get("id"), "result": {"echo": req.get("method")}}), flush=True)
    """
)


def _compiled_repo(tmp_path: Path) -> Path:
    d = tmp_path / ".chock" / "compiled" / "no-secrets" / "mcp-gateway"
    d.mkdir(parents=True)
    (d / "gateway-gate.json").write_text(
        json.dumps(
            {
                "kind": "content_regex",
                "binds": "string-arguments",
                "action": "block",
                "message": "secret detected",
                "params": {"content_pattern": r"AKIA[A-Z0-9]{16}"},
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_proxy_blocks_matching_call_and_forwards_the_rest(tmp_path):
    repo = _compiled_repo(tmp_path)
    gw = Gateway(repo, [sys.executable, "-c", _ECHO_SERVER])
    gw.start_downstream(pipe_output=False)
    try:
        out = io.StringIO()

        blocked = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "write_file", "arguments": {"content": _FAKE_AWS_KEY}},
            }
        )
        forwarded = gw.handle_line(blocked, out)
        assert forwarded is False
        response = json.loads(out.getvalue())
        assert response["id"] == 7
        assert response["error"]["code"] == -32000
        assert "no-secrets" in response["error"]["message"]

        clean = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {"name": "write_file", "arguments": {"content": "hello"}},
            }
        )
        assert gw.handle_line(clean, io.StringIO()) is True
        assert gw.process is not None and gw.process.stdout is not None
        downstream_reply = json.loads(gw.process.stdout.readline())
        assert downstream_reply["id"] == 8

        init = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert gw.handle_line(init, io.StringIO()) is True
        assert json.loads(gw.process.stdout.readline())["id"] == 1
    finally:
        if gw.process:
            gw.process.terminate()


_RECEIPT_SERVER = textwrap.dedent(
    """
    import sys
    for line in sys.stdin:
        sys.stdout.write("GOT:" + line)
        sys.stdout.flush()
    """
)


def test_proxy_forwards_malformed_lines_to_downstream(tmp_path):
    repo = _compiled_repo(tmp_path)
    gw = Gateway(repo, [sys.executable, "-c", _RECEIPT_SERVER])
    gw.start_downstream(pipe_output=False)
    try:
        assert gw.handle_line("not json at all\n", io.StringIO()) is True
        assert gw.process is not None and gw.process.stdout is not None
        assert gw.process.stdout.readline() == "GOT:not json at all\n"
    finally:
        if gw.process:
            gw.process.terminate()


def test_gateway_run_requires_downstream(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "chock", "gateway", "run", "--repo", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "downstream" in proc.stderr


def test_gateway_run_refuses_when_no_compiled_tree(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "chock", "gateway", "run", "--repo", str(tmp_path), "--", "echo", "x"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "no compiled gates" in proc.stderr


def test_emitter_requires_tool_use_in_on(tmp_path):
    out = tmp_path / "mcp-gateway"
    out.mkdir()
    manifest = {
        "id": "gw-test",
        "hook": {
            "gate": {
                "kind": "content_regex",
                "on": ["commit"],
                "action": "block",
                "message": "m",
                "params": {"content_pattern": "x"},
            }
        },
    }
    assert emitter.emit(tmp_path, out, manifest) == []

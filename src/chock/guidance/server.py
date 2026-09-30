"""Newline-delimited JSON-RPC over stdio: an MCP server with one read-only tool, chock_guidance."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from chock import __version__
from chock.guidance import advise
from chock.guidance.source import GuidanceError

TOOL = "chock_guidance"
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602
INTERNAL_ERROR = -32603

_DESCRIPTION = (
    "Read-only guidance, not enforcement. Before writing Java code, pass your plan and the repo-relative paths "
    "you will touch; "
    "returns the repo's installed rules that plan touches, each with its verdict (deny|ask) and the rule's own "
    "constraint text, which names the fix where the catalog records one. Reads only .agents/policies, the "
    "selection files and .chock/config.yaml in this repo; changes nothing. An empty result is not a clearance."
)


def tool_definition(limits: dict[str, int]) -> dict[str, Any]:
    return {
        "name": TOOL,
        "description": _DESCRIPTION,
        "inputSchema": {
            "type": "object",
            "properties": {
                "plan": {"type": "string", "maxLength": limits["plan_chars"]},
                "paths": {
                    "type": "array",
                    "maxItems": limits["paths"],
                    "items": {"type": "string", "maxLength": limits["path_chars"]},
                },
            },
            "required": ["plan", "paths"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    }


def _valid_id(value: object) -> bool:
    """JSON-RPC ids this server echoes: a string, an integer or null (never an object, a float or NaN)."""
    return value is None or isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool))


def _refusal(message: object) -> dict[str, Any] | None:
    """The error for a message that is not a request this server can answer, or None."""
    request_id = message.get("id") if isinstance(message, dict) else None
    if not _valid_id(request_id):
        return _error(None, INVALID_REQUEST, "id must be a string, an integer or null")
    valid = isinstance(message, dict) and message.get("jsonrpc") == "2.0" and isinstance(message.get("method"), str)
    return None if valid else _error(request_id, INVALID_REQUEST, "invalid request")


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_result(payload: dict[str, Any], *, is_error: bool) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "structuredContent": payload,
        "isError": is_error,
    }


class Server:
    def __init__(self, repo: Path) -> None:
        self.repo = Path(repo)
        self.limits = advise.data()["limits"]

    def _call(self, params: object) -> dict[str, Any]:
        if not isinstance(params, dict) or params.get("name") != TOOL:
            msg = f"unknown tool; the only tool is {TOOL}"
            raise GuidanceError(msg)
        arguments = params.get("arguments")
        if not isinstance(arguments, dict) or set(arguments) != {"plan", "paths"}:
            return _tool_result({"errors": ["arguments must be an object with exactly plan and paths"]}, is_error=True)
        try:
            payload = advise.guidance(self.repo, arguments.get("plan"), arguments.get("paths"))
        except GuidanceError as exc:
            return _tool_result({"errors": [str(exc)]}, is_error=True)
        return _tool_result(payload, is_error=bool(payload["errors"]))

    def _initialize(self, params: object) -> dict[str, Any]:
        asked = params.get("protocolVersion") if isinstance(params, dict) else None
        return {
            "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "chock", "version": __version__},
        }

    def _handlers(self) -> dict[str, Callable[[object], dict[str, Any]]]:
        return {
            "initialize": self._initialize,
            "ping": lambda _params: {},
            "tools/list": lambda _params: {"tools": [tool_definition(self.limits)]},
            "tools/call": self._call,
        }

    def handle(self, message: object) -> dict[str, Any] | None:
        """The response to one decoded message, or None for a notification. Never raises: whatever the repo
        holds, a request gets an answer and the server keeps serving."""
        refused = _refusal(message)
        if refused is not None:
            return refused
        if "id" not in message:
            return None
        request_id = message["id"]
        handler = self._handlers().get(message["method"])
        if handler is None:
            return _error(request_id, METHOD_NOT_FOUND, f"method not found: {message['method']}")
        try:
            return _result(request_id, handler(message.get("params")))
        except GuidanceError as exc:
            return _error(request_id, INVALID_PARAMS, str(exc))
        except Exception as exc:  # noqa: BLE001 -- a request always gets an answer; the server never dies on repo content
            return _error(request_id, INTERNAL_ERROR, f"internal error ({type(exc).__name__})")

    def handle_line(self, line: str) -> dict[str, Any] | None:
        try:
            message = json.loads(line)
        except (json.JSONDecodeError, RecursionError):
            return _error(None, PARSE_ERROR, "parse error")
        return self.handle(message)

    def serve(self, stdin: BinaryIO, stdout: TextIO) -> int:
        """Answer each line until EOF. A line over the byte cap is refused, never buffered whole."""
        cap = self.limits["line_bytes"]
        while raw := stdin.readline(cap + 1):
            if len(raw) > cap and not raw.endswith(b"\n"):
                while (rest := stdin.readline(cap)) and not rest.endswith(b"\n"):
                    continue
                response = _error(None, INVALID_REQUEST, "request line too large")
            elif not raw.strip():
                continue
            else:
                response = self.handle_line(raw.decode("utf-8", errors="replace"))
            if response is not None:
                stdout.write(json.dumps(response) + "\n")
                stdout.flush()
        return 0


def main(repo: Path) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return Server(repo).serve(sys.stdin.buffer, sys.stdout)

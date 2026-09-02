"""Stdio JSON-RPC interceptor: one gateway process wraps one downstream MCP server."""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, TextIO

from chock.gateway.gates import evaluate, load_gates

BLOCKED_CODE = -32000


def _blocked_response(request_id: Any, message: str) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": BLOCKED_CODE, "message": f"chock gateway refused this call: {message}"},
        }
    )


def _force_utf8(stream: Any) -> None:
    """Best-effort: pin a text stream to UTF-8 with replacement."""
    with contextlib.suppress(AttributeError, ValueError, OSError):
        stream.reconfigure(encoding="utf-8", errors="replace")


class Gateway:
    def __init__(self, repo_root: Path, downstream_argv: list[str]) -> None:
        self.repo_root = Path(repo_root)
        self.gates = load_gates(self.repo_root)
        self.downstream_argv = downstream_argv
        self.process: subprocess.Popen[str] | None = None
        self._out_lock = threading.Lock()
        self._downstream_ended = threading.Event()

    def _write_out(self, line: str, stream: TextIO) -> None:
        with self._out_lock:
            stream.write(line if line.endswith("\n") else line + "\n")
            stream.flush()

    def start_downstream(self, *, pipe_output: bool = True) -> None:
        """Spawn the wrapped server. `pipe_output=False` is for tests that read the"""
        self.process = subprocess.Popen(
            self.downstream_argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        if pipe_output:
            threading.Thread(target=self._pipe_downstream, daemon=True).start()

    def _pipe_downstream(self) -> None:
        assert self.process and self.process.stdout
        for line in self.process.stdout:
            self._write_out(line, sys.stdout)
        self._downstream_ended.set()
        with contextlib.suppress(OSError, ValueError):
            sys.stdin.close()

    def _block_message(self, item: Any) -> str | None:
        """Block message for a single request object, or None to allow it."""
        if not isinstance(item, dict) or item.get("method") != "tools/call":
            return None
        params = item.get("params")
        if not isinstance(params, dict):
            return "tools/call params is not an object; refusing (fail closed)"
        return evaluate(self.gates, str(params.get("name", "")), params.get("arguments"))

    def _screen(self, payload: Any) -> tuple[bool, str | None]:
        """(block?, response-to-write). A blocked notification blocks with no response."""
        if isinstance(payload, list):
            per_item = [(item, self._block_message(item)) for item in payload]
            if not any(msg is not None for _, msg in per_item):
                return False, None
            errors = []
            for item, msg in per_item:
                if isinstance(item, dict) and "id" in item:
                    reason = msg or "batch refused: another element in this batch was blocked (fail closed)"
                    errors.append(json.loads(_blocked_response(item.get("id"), reason)))
            return True, (json.dumps(errors) if errors else None)
        message = self._block_message(payload)
        if message is None:
            return False, None
        if not (isinstance(payload, dict) and "id" in payload):
            return True, None
        return True, _blocked_response(payload.get("id"), message)

    def handle_line(self, line: str, out: TextIO) -> bool:
        """Evaluate one client line. Returns True when it was forwarded downstream."""
        stripped = line.strip()
        if stripped:
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                payload = None
            if payload is not None:
                block, response = self._screen(payload)
                if block:
                    if response is not None:
                        self._write_out(response, out)
                    return False
        if self.process and self.process.stdin:
            try:
                self.process.stdin.write(line if line.endswith("\n") else line + "\n")
                self.process.stdin.flush()
            except (OSError, ValueError):
                self._downstream_ended.set()
                return False
        return True

    def serve(self) -> int:
        _force_utf8(sys.stdin)
        _force_utf8(sys.stdout)
        self.start_downstream()
        try:
            for line in sys.stdin:
                if self._downstream_ended.is_set():
                    break
                self.handle_line(line, sys.stdout)
        except (KeyboardInterrupt, BrokenPipeError, OSError, ValueError):
            pass
        finally:
            if self.process and self.process.poll() is None:
                self.process.terminate()
        if self.process is not None:
            try:
                return self.process.wait(timeout=5) or 0
            except subprocess.TimeoutExpired:
                self.process.kill()
                return 1
        return 0

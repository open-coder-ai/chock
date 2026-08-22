"""Stdio JSON-RPC interceptor: one gateway process wraps one downstream MCP server.

The client spawns this process instead of the real server (its command moves into the
gateway's argv). Every `tools/call` request is evaluated against the repo's compiled
gateway gates before it is forwarded; a blocked call is answered with a JSON-RPC error
and never reaches the downstream. Everything else -- initialize, tools/list, responses,
notifications -- passes through untouched.

One downstream per gateway process, deliberately: MCP is a one-server-per-connection
protocol, so aggregation (many upstreams behind one proxy, tool-name routing, merged
tools/list) is a protocol feature of its own and belongs to P3c with the config
witnesses. A repo wraps N servers with N gateway entries today.

Fail posture: fail closed by construction. If this process dies, the client's MCP calls
error; a gate spec that is unreadable, unknown, or evaluates a call as blocked refuses;
a batch request is screened element by element; a `tools/call` with non-object params is
refused rather than crashing the proxy. Stdio is forced to UTF-8 with replacement so a
non-ASCII payload cannot kill a stream thread. Line-buffered with explicit flushes --
buffered pipes deadlock.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, TextIO

from chock.gateway.gates import evaluate, load_gates

BLOCKED_CODE = -32000  # JSON-RPC server-defined error range


def _blocked_response(request_id: Any, message: str) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": BLOCKED_CODE, "message": f"chock gateway refused this call: {message}"},
        }
    )


def _force_utf8(stream: Any) -> None:
    """Best-effort: pin a text stream to UTF-8 with replacement.

    The downstream pipes are opened UTF-8, but the gateway's own stdio defaults to the
    locale encoding (cp1252 on Windows, this project's primary platform). A CJK/emoji
    tool result would then raise UnicodeEncodeError inside the pump thread and silently
    stall every later response. `errors='replace'` also means no single character can
    kill a stream.
    """
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        # Best-effort: a stream that cannot be reconfigured (already detached, or not a
        # standard text wrapper) keeps its current encoding. Nothing to recover here.
        pass


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
        """Spawn the wrapped server. `pipe_output=False` is for tests that read the
        downstream's stdout directly -- the pump thread and a direct reader racing on one
        stream would each get half the lines."""
        self.process = subprocess.Popen(
            self.downstream_argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,  # line buffered; without it the response pipe deadlocks
        )
        if pipe_output:
            threading.Thread(target=self._pipe_downstream, daemon=True).start()

    def _pipe_downstream(self) -> None:
        assert self.process and self.process.stdout
        for line in self.process.stdout:
            self._write_out(line, sys.stdout)
        # Downstream closed its stdout: it has exited (or is about to). Record it and try
        # to unblock the stdin reader so the gateway does not linger while a client waits
        # forever on a response the dead server will never send.
        self._downstream_ended.set()
        try:
            sys.stdin.close()
        except (OSError, ValueError):
            # Closing stdin from this thread is a best-effort nudge to unblock the reader;
            # if the platform refuses it, serve()'s _downstream_ended check still ends the
            # loop on the next line.
            pass

    def _block_message(self, item: Any) -> str | None:
        """Block message for a single request object, or None to allow it.

        A tools/call whose params is not an object is refused rather than crashing
        (non-object params are legal JSON-RPC but uninspectable here)."""
        if not isinstance(item, dict) or item.get("method") != "tools/call":
            return None
        params = item.get("params")
        if not isinstance(params, dict):
            return "tools/call params is not an object; refusing (fail closed)"
        return evaluate(self.gates, str(params.get("name", "")), params.get("arguments"))

    def _refusal_for(self, payload: Any) -> str | None:
        """The JSON-RPC response to write back if `payload` is refused, else None.

        A batch (list) is screened element by element -- a malicious tools/call wrapped
        in a one-element array must not skip the gate. If ANY element is blocked the whole
        batch is refused (fail closed), but every request id in it still gets an error
        response so the client is not left waiting on the permitted siblings."""
        if isinstance(payload, list):
            per_item = [(item, self._block_message(item)) for item in payload]
            if not any(msg is not None for _, msg in per_item):
                return None
            errors = []
            for item, msg in per_item:
                if isinstance(item, dict) and "id" in item:
                    reason = msg or "batch refused: another element in this batch was blocked (fail closed)"
                    errors.append(json.loads(_blocked_response(item.get("id"), reason)))
            return json.dumps(errors)
        message = self._block_message(payload)
        if message is None:
            return None
        request_id = payload.get("id") if isinstance(payload, dict) else None
        return _blocked_response(request_id, message)

    def handle_line(self, line: str, out: TextIO) -> bool:
        """Evaluate one client line. Returns True when it was forwarded downstream."""
        stripped = line.strip()
        if stripped:
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                payload = None
            if payload is not None:
                refusal = self._refusal_for(payload)
                if refusal is not None:
                    self._write_out(refusal, out)
                    return False
        if self.process and self.process.stdin:
            try:
                self.process.stdin.write(line if line.endswith("\n") else line + "\n")
                self.process.stdin.flush()
            except (OSError, ValueError):
                # Downstream is gone (BrokenPipe on POSIX, OSError(22) on Windows). Stop
                # forwarding; serve() will surface the downstream's exit code.
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
            # Interrupt or a closed/broken stdio stream ends the session; the finally
            # block below terminates the downstream and the exit code is derived from it.
            pass
        finally:
            if self.process and self.process.poll() is None:
                self.process.terminate()
        # A downstream that crashed reports its own nonzero code; a clean shutdown is 0.
        if self.process is not None:
            try:
                return self.process.wait(timeout=5) or 0
            except subprocess.TimeoutExpired:
                self.process.kill()
                return 1
        return 0

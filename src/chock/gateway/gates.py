"""Load and evaluate compiled mcp-gateway gate specs against MCP tool-call payloads.

Scope honesty (chock#32): the gateway sees ONLY what crosses it -- the arguments of MCP
tool calls routed through the proxy. It never sees an agent's native shell or file
tools, so nothing here claims to. Evaluators exist for exactly the kinds the emitter
publishes (mcp_gateway.RUNTIME_KINDS); tests assert the two stay in lockstep.

Fail-closed is the rule, uniformly: an unreadable gate, an unknown kind, a stripped
allowlist AND a stripped pattern all refuse. A live boundary has no human reviewing the
tool call, so a spec that could only be empty through tampering blocks rather than passes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote

GATEWAY_DIRNAME = "mcp-gateway"
GATE_FILENAME = "gateway-gate.json"

# Capture the AUTHORITY of every URL: after a scheme (`scheme://`) or scheme-relative at
# a left boundary (`//host`), up to the first path/query/fragment/delimiter. Two anchors,
# not one greedy run, so a URL embedded in a query (`?next=http://evil.io`) is its own
# match while a path's `//` (`https://ok.com/a//b`) is not re-read as a host. Any scheme
# matches -- ws/wss/ftp/file/gopher egress as readily as http.
_AUTHORITY_RE = re.compile(
    r"""(?:(?:[a-z][a-z0-9+.\-]*:)//|(?:^|[\s"'<>=(),|])//)([^/?#\s"'<>()|\\]*)""",
    re.IGNORECASE,
)

# A string argument that IS a bare endpoint (`evil.io`, `www.evil.io:8080`, `evil.io/x`)
# with no scheme -- common for MCP fetch/shell tools. Anchored to the whole trimmed value
# so a domain mentioned mid-prose ("see evil.io for docs") is NOT matched: only a value
# that stands alone as an endpoint. Requires a dotted name with a 2+ letter final label.
_BARE_ENDPOINT_RE = re.compile(
    r"""^(?:[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?\.)+[a-z]{2,}(?::\d+)?(?:/[^\s]*)?$""",
    re.IGNORECASE,
)


def load_gates(repo_root: Path) -> list[dict[str, Any]]:
    """Every compiled gateway gate in the repo, with its policy id attached."""
    compiled = Path(repo_root) / ".chock" / "compiled"
    gates: list[dict[str, Any]] = []
    if not compiled.is_dir():
        return gates
    for gate_file in sorted(compiled.glob(f"*/{GATEWAY_DIRNAME}/{GATE_FILENAME}")):
        try:
            spec = json.loads(gate_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # An unreadable gate cannot be silently skipped -- that would let a corrupted
            # spec disable enforcement. Surface it as a blocking pseudo-gate instead.
            gates.append(
                {
                    "kind": "unreadable",
                    "policy_id": gate_file.parent.parent.name,
                    "message": f"gateway gate unreadable: {gate_file}",
                }
            )
            continue
        spec["policy_id"] = gate_file.parent.parent.name
        gates.append(spec)
    return gates


def _string_values(value: Any) -> Iterator[str]:
    """Every string leaf in a JSON-shaped arguments object."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _string_values(v)
    elif isinstance(value, list):
        for v in value:
            yield from _string_values(v)


def _hosts_in(text: str) -> Iterator[str]:
    """Every authority in every URL-ish token, across the raw and percent-decoded text.

    Yields "" for a URL that has no host (e.g. file:///etc/passwd) so the caller can fail
    it closed rather than skip it.
    """
    seen: set[str] = set()

    def _emit(authority: str) -> Iterator[str]:
        authority = authority.rsplit("@", 1)[-1]  # drop any userinfo
        if authority.startswith("["):  # IPv6 literal [::1]:port
            host = authority[1:].split("]", 1)[0]
        else:
            host = authority.split(":", 1)[0]  # drop :port
        host = host.lower()
        key = host or "\x00no-host"
        if key not in seen:
            seen.add(key)
            yield host

    for hay in (text, unquote(text)):
        for match in _AUTHORITY_RE.finditer(hay):
            yield from _emit(match.group(1))
        # A whole value that is itself a bare host/endpoint (no scheme, no `//`).
        stripped = hay.strip()
        if _BARE_ENDPOINT_RE.match(stripped):
            yield from _emit(stripped.split("/", 1)[0])


def _eval_content_regex(spec: dict[str, Any], arguments: Any) -> str | None:
    params = spec.get("params") or {}
    pattern = params.get("content_pattern") or ""
    if not pattern:
        # minLength 1 in the schema, so an empty pattern in compiled output is tampering
        # or emitter breakage -- fail closed, matching egress_allowlist's empty-list rule.
        return str(spec.get("message") or "content_regex pattern is empty; refusing (fail closed)")
    # allowlist_pragma is deliberately NOT honored at the gateway: the scanned text is the
    # live, fully attacker-controlled tool-call argument, so an appended pragma token would
    # neutralize the scan. The pragma is a git-diff-review concept (a human sees it); the
    # gateway has no reviewer, so a match always blocks.
    for text in _string_values(arguments):
        for line in text.splitlines() or [""]:
            if re.search(pattern, line):
                return str(spec.get("message") or f"content matched forbidden pattern ({pattern})")
    return None


def _eval_egress_allowlist(spec: dict[str, Any], arguments: Any) -> str | None:
    params = spec.get("params") or {}
    allowed = [h.lower().lstrip(".") for h in params.get("allowed_hosts") or []]
    if not allowed:
        # Silently allowing all egress under a policy named "allowlist" is the worse
        # failure; schema requires >=1 host, so a stripped list is tampering. Fail closed.
        return str(spec.get("message") or "egress allowlist is empty; refusing all egress")
    for text in _string_values(arguments):
        for host in _hosts_in(text):
            if not host or not any(host == a or host.endswith("." + a) for a in allowed):
                shown = host or "<no-host URL>"
                return str(spec.get("message") or "") + f" [blocked egress: {shown}]"
    return None


_EVALUATORS = {
    "content_regex": _eval_content_regex,
    "egress_allowlist": _eval_egress_allowlist,
}

#: Exported so tests can assert emitter RUNTIME_KINDS == evaluator coverage.
RUNTIME_KINDS = tuple(sorted(_EVALUATORS))


def evaluate(gates: list[dict[str, Any]], tool_name: str, arguments: Any) -> str | None:
    """First blocking message across all gates, or None to allow.

    Unknown kinds block: a spec this runtime cannot evaluate means version skew between
    compiled output and the proxy, and allowing traffic under skew is fail-open.
    """
    for spec in gates:
        kind = spec.get("kind")
        evaluator = _EVALUATORS.get(kind or "")
        if evaluator is None:
            return f"[{spec.get('policy_id', '?')}] unevaluable gateway gate kind {kind!r}; refusing (fail closed)"
        message = evaluator(spec, arguments)
        if message:
            return f"[{spec.get('policy_id', '?')}] {message}"
    return None

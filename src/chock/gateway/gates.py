"""Load and evaluate compiled mcp-gateway gate specs against MCP tool-call payloads."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote

GATEWAY_DIRNAME = "mcp-gateway"
GATE_FILENAME = "gateway-gate.json"

_AUTHORITY_RE = re.compile(
    r"""(?:(?:[a-z][a-z0-9+.\-]*:)//|(?:^|[\s"'<>=(),|])//)([^/?#\s"'<>()|\\]*)""",
    re.IGNORECASE,
)

_DOTTED_DNS = r"(?:[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?\.)+[a-z]{2,}\.?"
_IPV4 = r"\d{1,3}(?:\.\d{1,3}){3}"
_IPV6 = r"\[[0-9a-f:]+\]"
_BARE_ENDPOINT_RE = re.compile(
    rf"^(?:(?:{_DOTTED_DNS}|{_IPV4}|{_IPV6})(?::\d+)?"
    rf"|localhost(?::\d+)?"
    rf"|[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?:\d+)"
    rf"(?:[/?#][^\s]*)?$",
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
    """Every authority in every URL-ish token, across the raw and percent-decoded text."""
    seen: set[str] = set()

    def _emit(authority: str) -> Iterator[str]:
        authority = authority.rsplit("@", 1)[-1]
        if authority.startswith("["):
            host = authority[1:].split("]", 1)[0]
        else:
            host = authority.split(":", 1)[0]
        host = host.lower().rstrip(".")
        key = host or "\x00no-host"
        if key not in seen:
            seen.add(key)
            yield host

    for hay in (text, unquote(text)):
        for match in _AUTHORITY_RE.finditer(hay):
            yield from _emit(match.group(1))
        stripped = hay.strip()
        if _BARE_ENDPOINT_RE.match(stripped):
            authority = re.split(r"[/?#]", stripped, maxsplit=1)[0]
            yield from _emit(authority)


def _eval_content_regex(spec: dict[str, Any], arguments: Any) -> str | None:
    params = spec.get("params") or {}
    pattern = params.get("content_pattern") or ""
    if not pattern:
        return str(spec.get("message") or "content_regex pattern is empty; refusing (fail closed)")
    for text in _string_values(arguments):
        for line in text.splitlines() or [""]:
            if re.search(pattern, line):
                return str(spec.get("message") or f"content matched forbidden pattern ({pattern})")
    return None


def _eval_egress_allowlist(spec: dict[str, Any], arguments: Any) -> str | None:
    params = spec.get("params") or {}
    allowed = [h.lower().strip(".") for h in params.get("allowed_hosts") or []]
    if not allowed:
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

RUNTIME_KINDS = tuple(sorted(_EVALUATORS))


def evaluate(gates: list[dict[str, Any]], tool_name: str, arguments: Any) -> str | None:
    """First blocking message across all gates, or None to allow."""
    for spec in gates:
        kind = spec.get("kind")
        evaluator = _EVALUATORS.get(kind or "")
        if evaluator is None:
            return f"[{spec.get('policy_id', '?')}] unevaluable gateway gate kind {kind!r}; refusing (fail closed)"
        message = evaluator(spec, arguments)
        if message:
            return f"[{spec.get('policy_id', '?')}] {message}"
    return None

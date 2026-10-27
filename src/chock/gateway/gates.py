"""Load and evaluate compiled mcp-gateway gate specs against MCP tool-call payloads."""

from __future__ import annotations

import fnmatch
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote

from chock.gate.outside_repo import platform_case_blind
from chock.gate.session_log import SESSION_PATH_KEYS

GATEWAY_DIRNAME = "mcp-gateway"
GATE_FILENAME = "gateway-gate.json"

# A web scheme takes any run of slashes (browsers read `https:/x` and `https:///x` as `https://x`);
# the authority runs to the first delimiter, backslash included so `a\@b` keeps the reading curl gives it.
_AUTHORITY_RE = re.compile(
    r"""(?:(?:https?|wss?|ftp):/+|(?:[a-z][a-z0-9+.\-]*:)//|(?:^|[\s"'<>=(),|])//)([^/?#\s"'<>()|]*)""",
    re.IGNORECASE,
)
_HOST_RE = re.compile(r"^(?:[a-z0-9_\-.]+|[0-9a-f:.]+)$")

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
        spec["repo_root"] = str(repo_root)
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
        host = authority[1:].split("]", 1)[0] if authority.startswith("[") else authority.split(":", 1)[0]
        host = host.lower().rstrip(".")
        key = host or "\x00no-host"
        if key not in seen:
            seen.add(key)
            yield host

    decoded = unquote(text)
    for hay in (text, decoded, text.replace("\\", "/"), decoded.replace("\\", "/")):
        for match in _AUTHORITY_RE.finditer(hay):
            yield from _emit(match.group(1))
        stripped = hay.strip()
        if _BARE_ENDPOINT_RE.match(stripped):
            authority = re.split(r"[/?#]", stripped, maxsplit=1)[0]
            yield from _emit(authority)


def _blind(spec: dict[str, Any]) -> bool:
    """Whether the gate compares paths without regard to case: the spec's word, else this machine's default."""
    flag = spec.get("case_blind")
    return flag if isinstance(flag, bool) else platform_case_blind()


def _call_paths(spec: dict[str, Any], arguments: Any) -> list[str]:
    """Write targets the call names, repo-relative: the same argument keys the session log reads."""
    if not isinstance(arguments, dict):
        return []
    root = str(spec.get("repo_root") or "").replace("\\", "/").rstrip("/")
    paths: list[str] = []
    for key in SESSION_PATH_KEYS:
        value = arguments.get(key)
        if not isinstance(value, str) or not value:
            continue
        path = value.replace("\\", "/")
        prefix = root + "/"
        if root and (path.casefold().startswith(prefix.casefold()) if _blind(spec) else path.startswith(prefix)):
            path = path[len(root) + 1 :]
        paths.append(path.removeprefix("./"))
    return paths


def _eval_content_regex(spec: dict[str, Any], arguments: Any) -> str | None:
    params = spec.get("params") or {}
    pattern = params.get("content_pattern") or ""
    if not pattern:
        return str(spec.get("message") or "content_regex pattern is empty; refusing (fail closed)")
    message = str(spec.get("message") or f"content matched forbidden pattern ({pattern})")
    scope = spec.get("paths") or []
    paths = _call_paths(spec, arguments)
    if scope:
        # A path-bounded gate judges only what it can place inside its bound.
        fold = str.casefold if _blind(spec) else str
        paths = [p for p in paths if any(fnmatch.fnmatchcase(fold(p), fold(g)) for g in scope)]
        if not paths:
            return None
    forbidden = params.get("forbidden_path_regex")
    if forbidden and any(re.search(forbidden, p, re.IGNORECASE if _blind(spec) else 0) for p in paths):
        return message
    # allowlist_pragma is deliberately not honoured: the gateway is an agent-side surface,
    # and a waiver the agent writes into its own tool call must never lift the block.
    for text in _string_values(arguments):
        for line in text.splitlines() or [""]:
            if re.search(pattern, line):
                return message
    return None


def _eval_egress_allowlist(spec: dict[str, Any], arguments: Any) -> str | None:
    params = spec.get("params") or {}
    allowed = [h.lower().strip(".") for h in params.get("allowed_hosts") or []]
    if not allowed:
        return str(spec.get("message") or "egress allowlist is empty; refusing all egress")
    for text in _string_values(arguments):
        for raw in _hosts_in(text):
            host = _ascii_host(raw)
            if host is None:
                return str(spec.get("message") or "") + " [blocked egress: undecidable host]"
            if not host or not any(host == a or host.endswith("." + a) for a in allowed):
                shown = host or "<no-host URL>"
                return str(spec.get("message") or "") + f" [blocked egress: {shown}]"
    return None


def _ascii_host(host: str) -> str | None:
    """The host as DNS would see it, or None when no resolver could: that is a block, not a match."""
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            return None
    return host if not host or _HOST_RE.match(host) else None


_EVALUATORS = {
    "content_regex": _eval_content_regex,
    "egress_allowlist": _eval_egress_allowlist,
}

RUNTIME_KINDS = tuple(sorted(_EVALUATORS))


#: A finding no gate decided: the gate could not be read, run or judged, so the call is refused.
FAULT = "fault"


def judge(
    gates: list[dict[str, Any]], _tool_name: str, arguments: Any, *, case_blind: bool | None = None
) -> list[tuple[str, str, str]]:
    """(policy_id, action, message) for every gate that fires, in order; `fault` when a gate cannot judge.

    `case_blind` says whether paths compare without regard to case; this machine's default unless told.
    """
    findings: list[tuple[str, str, str]] = []
    for spec in gates:
        policy = str(spec.get("policy_id", "?"))
        kind = spec.get("kind")
        evaluator = _EVALUATORS.get(kind or "")
        if evaluator is None:
            findings.append((policy, FAULT, f"unevaluable gateway gate kind {kind!r}; refusing (fail closed)"))
            continue
        try:
            message = evaluator(spec if case_blind is None else {**spec, "case_blind": case_blind}, arguments)
        except Exception as exc:  # noqa: BLE001 -- a gate that cannot run refuses the call, never allows it
            findings.append((policy, FAULT, f"gateway gate failed ({type(exc).__name__}); refusing (fail closed)"))
            continue
        if message:
            findings.append((policy, str(spec.get("action") or "block"), message))
    return findings


def evaluate(
    gates: list[dict[str, Any]], tool_name: str, arguments: Any, *, case_blind: bool | None = None
) -> str | None:
    """First blocking message across all gates, or None to allow."""
    return refusal(judge(gates, tool_name, arguments, case_blind=case_blind))


def refusal(findings: list[tuple[str, str, str]]) -> str | None:
    """The first finding that blocks, as the client reads it; each warn before it goes to stderr."""
    for policy, action, message in findings:
        text = f"[{policy}] {message}"
        if action == "warn":
            # A warning never blocks: the call goes through and the operator's stderr has the words.
            sys.stderr.write(f"chock: warning: {text}\n")
            continue
        # `ask` blocks: a proxy on a pipe has no person to ask.
        return f"{text} (asks a person; the gateway cannot prompt, so it blocks)" if action == "ask" else text
    return None

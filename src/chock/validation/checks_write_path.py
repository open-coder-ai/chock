"""DET-6: a guard's or an event script's Edit/Write door is a declared tool_use gate, never implied."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.compile.emitters import SCRIPT_EVENTS
from chock.compile.emitters.in_agent import TOOL_USE, _guard_script
from chock.manifest import CANONICAL_MANIFEST, resolve_manifest_path
from chock.validation.report import Finding, Report

_CATEGORY = "manifest_write_path"

#: The documented path-only idiom: a content pattern that matches nothing, so only
#: `forbidden_path_regex` can refuse. Exact text only; other never-matching patterns are not
#: recognised (spec/script-backed-gates.md, "Write-path door").
NEVER_MATCHES = "(?!)"

_REMEDY = (
    'for the Edit/Write door add a hook.gate with "on" including tool_use: kind: script '
    "(params.script names a .py judged on the written files) for logic, or kind: content_regex "
    f"with params.forbidden_path_regex and content_pattern '{NEVER_MATCHES}' to refuse any write to a path"
)


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _script_event_problems(script: dict[str, Any]) -> list[str]:
    """A git-hook script runs at its git event only; any other event it names is never wired."""
    return [
        f"hook.script cannot run at '{event}': a script runs only from the git hook "
        f"({', '.join(SCRIPT_EVENTS)}), never in the agent or CI; {_REMEDY}"
        for event in _list(script.get("on"))
        if event not in SCRIPT_EVENTS
    ]


def _path_gate_problems(gate: dict[str, Any], guard: str | None) -> list[str]:
    """A path-only gate needs a path; next to a guard it is the write-path door, so needs tool_use."""
    params = _dict(gate.get("params"))
    if gate.get("kind") != "content_regex" or params.get("content_pattern") != NEVER_MATCHES:
        return []
    if not params.get("forbidden_path_regex"):
        return [
            f"content_pattern '{NEVER_MATCHES}' never matches and params.forbidden_path_regex is "
            "missing or empty, so this gate can never refuse anything; name the protected paths "
            "in forbidden_path_regex, or use a content_pattern that can match"
        ]
    if guard and TOOL_USE not in _list(gate.get("on")):
        return [
            f"this path gate pairs with the shell guard implementations/{guard}, which sees shell "
            'commands only, but its "on" lacks tool_use, so Edit/Write to the protected paths '
            'go unchecked in the agent; add tool_use to "on"'
        ]
    return []


def check_write_path_pairing(artifact_dir: Path, manifest: dict[str, Any], _artifact_type: str, report: Report) -> None:
    """Refuse a hook shape that implies a write-path door it does not have."""
    hook = _dict(manifest.get("hook"))
    policy_id = str(manifest.get("id") or Path(artifact_dir).name)
    guard = _guard_script(Path(artifact_dir), policy_id)
    problems = _script_event_problems(_dict(hook.get("script")))
    problems += _path_gate_problems(_dict(hook.get("gate")), guard)
    ref = str(resolve_manifest_path(artifact_dir) or (Path(artifact_dir) / CANONICAL_MANIFEST))
    for problem in problems:
        report.add(Finding(ref, _CATEGORY, "error", problem))

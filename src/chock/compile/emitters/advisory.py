"""Derive a policy's agent-facing advisory text from the policy itself."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from chock.gate.build import build_gate_json

_VALUE_CHARS = 48
_PARAMS_CHARS = 120
_REGEX_SHORT = 60
_REGEX_SUFFIXES = ("_regex", "_pattern", "_pragma")
_GIT = shutil.which("git") or "git"

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def repo_root_from_output(output_dir: Path) -> Path:
    """Walk up from the output directory to the repo root that owns .chock."""
    path = Path(output_dir).resolve()
    for parent in [path, *path.parents]:
        if parent.name == ".chock" and parent.is_dir():
            return parent.parent
    try:
        out = subprocess.check_output(  # noqa: S603 -- finding the repo root via git is this fallback's job
            [_GIT, "rev-parse", "--show-toplevel"], text=True
        )
        return Path(out.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


def _scalar(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        text = "|".join(str(v) for v in value)
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    return " ".join(text.split())


def template_message(message: str, params: dict[str, Any]) -> str:
    """Substitute `{param}` placeholders with resolved param values."""

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return _scalar(params[key]) if key in params else match.group(0)

    return _PLACEHOLDER.sub(replace, message)


def _clip(text: str) -> str:
    return text if len(text) <= _VALUE_CHARS else text[: _VALUE_CHARS - 3] + "..."


def _item(key: str, value: Any) -> str:
    """`k=v`; a regex past `_REGEX_SHORT` becomes `k(regex)`, never a pattern cut mid-way."""
    text = _scalar(value)
    if key.endswith(_REGEX_SUFFIXES) and len(text) > _REGEX_SHORT:
        return f"{key}(regex)"
    return f"{key}={_clip(text)}"


def _render_params(params: dict[str, Any]) -> str:
    """`k=v` pairs in manifest order, clipped to keep the line readable."""
    rendered: list[str] = []
    used = 0
    for key, value in params.items():
        # A script param's compiled value is the file's path from the repository root, which
        # depends on where the policy sits (`.agents/policies/<id>` once adopted, a catalog tree
        # before). The line an agent reads, and the packaged SKILL.md that carries it, must not
        # change with the address: the bare name is what the manifest declared.
        shown = Path(str(value)).name if key == "script" else value
        item = _item(key, shown)
        if rendered and used + len(item) > _PARAMS_CHARS:
            rendered.append("...")
            break
        rendered.append(item)
        used += len(item) + 1
    return " ".join(rendered)


def _first_line(text: str) -> str:
    return next((line.strip() for line in str(text).splitlines() if line.strip()), "")


def _gate_lines(spec: dict[str, Any]) -> list[str]:
    """`on(events): action(kind) params` plus the resolved block message."""
    events = "|".join(str(e) for e in spec.get("on") or []) or "any"
    head = f"on({events}): {spec.get('action') or 'block'}({spec.get('kind')})"
    # The bound comes first: it is what tells an agent which files the gate reaches.
    scope = f"paths={_scalar(spec['paths'])}" if spec.get("paths") else ""
    params = " ".join(part for part in (scope, _render_params(spec.get("params") or {})) if part)
    if params:
        head = f"{head} {params}"
    message = _first_line(template_message(str(spec.get("message") or ""), spec.get("params") or {}))
    return [head, message] if message else [head]


def policy_pointer(policy_dir: Path) -> str:
    """Where to edit this policy, as a repo-relative path."""
    parts = Path(policy_dir).resolve().parts
    if ".agents" in parts:
        start = len(parts) - 1 - parts[::-1].index(".agents")
        return "/".join(parts[start:]) + "/"
    return f".agents/policies/{Path(policy_dir).name}/"


def substitute_policy_vars(text: str, policy_dir: Path) -> str:
    """Resolve `{policy_dir}` in authored rule text to the policy's installed path."""
    return text.replace("{policy_dir}", policy_pointer(policy_dir).rstrip("/"))


def advisory_lines(policy_dir: Path, manifest: dict[str, Any], repo_root: Path) -> list[str]:
    """The <=2 lines describing this policy to an agent, or [] if the policy declares nothing."""
    rule_text = substitute_policy_vars(str((manifest.get("rule") or {}).get("text", "")), policy_dir)
    rule_lines = [line.strip() for line in rule_text.splitlines() if line.strip()]
    # A rule carrying a gate keeps its own words as the ambient surface; the gate is the same
    # control on another surface, not a replacement for what the rule tells the agent.
    if rule_lines and manifest.get("artifact") == "rule":
        return rule_lines[:2]

    spec = build_gate_json(policy_dir, repo_root)
    if spec is not None:
        return _gate_lines(spec)[:2]
    if rule_lines:
        return rule_lines[:2]

    description = _first_line(manifest.get("description") or "")
    if description:
        policy_id = manifest.get("id") or Path(policy_dir).name
        return [f"{manifest.get('enforcement') or 'advise'}({policy_id}): {description}"]

    return []

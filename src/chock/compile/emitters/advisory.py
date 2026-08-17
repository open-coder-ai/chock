"""Derive a policy's agent-facing advisory text from the policy itself.

The ambient rule used to be a four-entry dict keyed by policy id, which failed twice.

It went stale. `protect-main-branch` resolves `params.config_key` against
`.chock/config.yaml`, so an adopter setting `protected_branches: [main, release,
production]` gets a gate that blocks three branches and an ambient rule that still said
"main/master". The agent read AGENTS.md, concluded `production` was writable, and was then
blocked by a message naming the wrong branches -- the framework lying to the agent it
governs.

And -- the half that matters more -- it said nothing at all about any policy outside the
dict. v3 is built on drop-in third-party policies, and 10 of the 12 current baselines are
advise-tier, meaning the ambient rule is their ONLY enforcement surface. Every one of them
rendered as `on(any): enforce policy '<id>'`, so the entire user-visible output of a
dropped-in advisory policy was a line that conveys nothing.

Nothing here looks up a policy id. Text comes from the manifest plus the RESOLVED gate
spec, so a policy this code has never seen renders as well as a baseline one.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from chock.gate.build import build_gate_json

#: `short_code_english` forbids prose, and an ambient rule is capped at 2 lines. A gate
#: param can be a 700-character secret-scanning regex, so values are clipped rather than
#: allowed to turn one of those two lines into a wall.
_VALUE_CHARS = 48
_PARAMS_CHARS = 120

#: Only `{name}` where `name` is a resolved param is substituted. This is how a manifest
#: opts in to templating: an author who writes a literal message keeps it verbatim, because
#: a block message is often worded deliberately and must not be silently rewritten.
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def repo_root_from_output(output_dir: Path) -> Path:
    """Walk up from the output directory to the repo root that owns .chock."""
    path = Path(output_dir).resolve()
    for parent in [path, *path.parents]:
        if parent.name == ".chock" and parent.is_dir():
            return parent.parent
    try:
        return Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
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
    """Substitute `{param}` placeholders with resolved param values.

    Fixes C2: the manifest's static message for `protect-main-branch` said "(main/master)"
    even after config resolution changed which branches the gate blocks, so the block text
    named branches that were not the ones enforced. Substitution is deliberately partial --
    an unknown `{name}` is left alone rather than raising or blanking, because gate messages
    can legitimately contain braces (regex quantifiers) that are not placeholders.
    """

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return _scalar(params[key]) if key in params else match.group(0)

    return _PLACEHOLDER.sub(replace, message)


def _clip(text: str) -> str:
    return text if len(text) <= _VALUE_CHARS else text[: _VALUE_CHARS - 3] + "..."


def _render_params(params: dict[str, Any]) -> str:
    """`k=v` pairs in manifest order, clipped to keep the line readable."""
    rendered: list[str] = []
    used = 0
    for key, value in params.items():
        item = f"{key}={_clip(_scalar(value))}"
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
    params = _render_params(spec.get("params") or {})
    if params:
        head = f"{head} {params}"
    message = _first_line(template_message(str(spec.get("message") or ""), spec.get("params") or {}))
    return [head, message] if message else [head]


def policy_pointer(policy_dir: Path) -> str:
    """Where to edit this policy, as a repo-relative path.

    Built from the policy's actual directory rather than assembled from its id. The id-based
    form named `.agents/policies/<id>/` for every policy, but `init` installs baseline packs
    under `.agents/policies/_baseline/<id>/` -- so the pointer every adopter reads in their
    AGENTS.md has been sending agents to a path that does not exist.
    """
    parts = Path(policy_dir).resolve().parts
    if ".agents" in parts:
        start = len(parts) - 1 - parts[::-1].index(".agents")
        return "/".join(parts[start:]) + "/"
    return f".agents/policies/{Path(policy_dir).name}/"


def substitute_policy_vars(text: str, policy_dir: Path) -> str:
    """Resolve `{policy_dir}` in authored rule text to the policy's installed path.

    A rule that points at its own `references/` must name a path, but the same source lives
    at `base/<id>/` in a catalog and `.agents/policies/<id>/` in an adopter -- so authors
    were hardcoding one and being wrong in the other. `{policy_dir}` compiles to wherever
    this policy actually is, with no trailing slash so `{policy_dir}/references/x.md` reads
    naturally.
    """
    return text.replace("{policy_dir}", policy_pointer(policy_dir).rstrip("/"))


def advisory_lines(policy_dir: Path, manifest: dict[str, Any], repo_root: Path) -> list[str]:
    """The <=2 lines describing this policy to an agent, or [] if the policy declares nothing.

    Precedence is the order of enforcement strength: a resolved gate is what actually runs,
    `rule.text` is the authored short-code form for advise-tier policies (already written to
    the 2-line budget), and the description is the last thing that carries any meaning.
    """
    spec = build_gate_json(policy_dir, repo_root)
    if spec is not None:
        return _gate_lines(spec)[:2]

    rule_text = substitute_policy_vars(str((manifest.get("rule") or {}).get("text", "")), policy_dir)
    rule_lines = [line.strip() for line in rule_text.splitlines() if line.strip()]
    if rule_lines:
        return rule_lines[:2]

    description = _first_line(manifest.get("description") or "")
    if description:
        policy_id = manifest.get("id") or Path(policy_dir).name
        return [f"{manifest.get('enforcement') or 'advise'}({policy_id}): {description}"]

    return []

"""The `prompt_submit` fragments: the hook that runs when a person submits a prompt, before the model reads it.

Only vendors in `vendors.prompt_submit_vendors()` get an entry: those agentseam's matrix says can
refuse a prompt, whose hook config chock may write. The rest (detect-only, no event, home-anchored
config) get nothing, and their coverage says so. The hook carries no tool, so no matcher is written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock import vendors
from chock.compile.emitters.advisory import repo_root_from_output
from chock.compile.emitters.in_agent_hooks import adapter_rel, cursor_entry, generic_prompt_submit_config, hook_entry
from chock.emit import write_generated_json
from chock.gate.build import build_gate_json
from chock.gate.schema import PROMPT_SUBMIT_EVENT, PROMPT_SUBMIT_KINDS
from chock.hooks.launch import hook_command

PROMPT_SUBMIT_GATE_FILE = "prompt-submit-gate.json"
PROMPT_SUBMIT_FLAG = "--prompt-submit"
#: The claude fragment, named apart because it lands under its own event key in the settings file.
CLAUDE_FRAGMENT = "prompt-submit.json"
SURFACE = "prompt-submit"


def prompt_submit_gate_spec(policy_dir: Path, repo_root: Path) -> dict[str, Any] | None:
    """The compiled gate this policy wants run per prompt, or None: no `prompt_submit` event, or a kind that cannot."""
    spec = build_gate_json(policy_dir, repo_root)
    if spec is None or PROMPT_SUBMIT_EVENT not in spec.get("on", []):
        return None
    return spec if spec.get("kind") in PROMPT_SUBMIT_KINDS else None


def _fragment(vendor: str, command: str) -> tuple[str, Any]:
    if vendor == "claude_code":
        return CLAUDE_FRAGMENT, hook_entry(command)
    if vendors.hook_entry_flat(vendor):
        return f"{vendor}-hooks.json", {vendors.prompt_submit_event(vendor): [cursor_entry(command, fail_closed=True)]}
    return f"{vendor}-hooks.json", generic_prompt_submit_config(vendor, command)


def emit(policy_dir: Path, output_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """Write the gate and one fragment per prompt-submit vendor; nothing for a policy with no such gate."""
    spec = prompt_submit_gate_spec(policy_dir, repo_root_from_output(output_dir))
    if spec is None:
        return []
    policy_id = str(manifest.get("id", policy_dir.name))
    output_dir.mkdir(parents=True, exist_ok=True)
    gate = output_dir / PROMPT_SUBMIT_GATE_FILE
    write_generated_json(gate, spec)
    written = [gate]
    reference = f".chock/compiled/{policy_id}/{SURFACE}/{PROMPT_SUBMIT_GATE_FILE}"
    for vendor in vendors.prompt_submit_vendors():
        name, doc = _fragment(vendor, hook_command(adapter_rel(vendor), PROMPT_SUBMIT_FLAG, reference))
        write_generated_json(output_dir / name, doc)
        written.append(output_dir / name)
    return written

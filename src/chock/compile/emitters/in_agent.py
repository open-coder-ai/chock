"""The one in-agent emitter: hook fragments for every wired vendor, wire facts from vendor config."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from chock import vendors
from chock.compile.emitters import GUARD_SUFFIXES, policy_rel_path
from chock.compile.emitters.advisory import repo_root_from_output
from chock.compile.emitters.in_agent_hooks import TIMEOUT_SECONDS, cursor_entry, generic_hooks_file, hook_entry
from chock.emit import write_generated_json
from chock.gate.build import build_gate_json
from chock.gate.runner import WRITE_PATH_KINDS
from chock.hooks.launch import hook_command

GUARD_SCRIPTS = {
    "block-destructive-commands": "block-destructive.sh",
    "block-no-verify": "block-no-verify.sh",
}


def _guard_script(policy_dir: Path, policy_id: str) -> str | None:
    """The policy's guard script name, by convention first, legacy map second."""
    impl = policy_dir / "implementations"
    for suffix in GUARD_SUFFIXES:
        if (impl / f"{policy_id}{suffix}").exists():
            return f"{policy_id}{suffix}"
    legacy = GUARD_SCRIPTS.get(policy_id)
    if legacy and (impl / legacy).exists():
        return legacy
    return None


#: claude_code's own recorded shell vocabulary, used for its claude-plugin hooks file.
MATCHER = vendors.shell_matcher("claude_code")
assert MATCHER is not None  # noqa: S101 -- import-time upstream-data invariant, not request handling

# Witnessed overrides: chock's agent-hooks file speaks `preToolUse` with bash/powershell/
# timeoutSec entry keys (live deny, data/witnesses.json: vscode_copilot x agent-hooks);
# agentseam 0.2.0 records `PreToolUse` with {type, command, windows} instead. The facts
# stay here until upstream ingests the witnessed shape; tests/test_vendor_wire_facts.py
# pins the disagreement so its resolution surfaces loudly.
AGENT_HOOKS_EVENT = "preToolUse"
AGENT_HOOKS_ENVELOPE = {"version": 1}
SHELL_MATCHER = "bash|powershell|pwsh|sh|shell"

#: The content fragment claude_code's installer merges, named apart from the shell one so a
#: policy could one day carry both without either overwriting the other.
WRITE_FRAGMENT = "pretooluse-write.json"


def _adapter_rel(vendor: str) -> str:
    """Where the vendored runtime lives in a consumer repo: chock's convention + agent id."""
    return f".chock/bin/{vendor}.py"


def _compiled_rel(policy_id: str) -> str:
    """Where this policy's pre-tool-use artifacts land, from chock's own compiled layout."""
    return f".chock/compiled/{policy_id}/pre-tool-use"


#: Vendors wired through hand-shaped fragments that predate the derivation (claude/cursor
#: entry shapes, the witnessed agent-hooks override). Everyone else the membership
#: predicate admits renders through agentseam's own hook_config -- no per-vendor emitter.
BESPOKE_VENDORS = ("claude_code", "cursor", "vscode_copilot")

GENERIC_VENDORS = tuple(v for v in vendors.in_agent_vendors() if v not in BESPOKE_VENDORS)


GATE_FILE = "gate.json"

#: A gate reaches this surface only when the policy asked for this event by name.
TOOL_USE = "tool_use"


def tool_use_gate_spec(policy_dir: Path, repo_root: Path) -> dict[str, Any] | None:
    """The compiled gate this policy wants run at tool use, or None when it wants none.

    Three ways to want none, each the policy's own statement rather than a judgement made
    here: no declarative gate at all, tool_use not among its declared events, or a kind
    asking a question a write cannot answer. The runner refuses that last case anyway, so
    emitting a hook certain to refuse would be installing noise.
    """
    spec = build_gate_json(policy_dir, repo_root)
    if spec is None or TOOL_USE not in spec.get("on", []):
        return None
    return spec if spec.get("kind") in WRITE_PATH_KINDS else None


def _tool_use_gate(policy_dir: Path, output_dir: Path) -> dict[str, Any] | None:
    return tool_use_gate_spec(policy_dir, repo_root_from_output(output_dir))


def _guard_fragments(policy_dir: Path, script: str, output_dir: Path) -> list[Path]:
    """The shell-command fragments, one per wired vendor. Behaviour unchanged."""
    guard = f"{policy_rel_path(policy_dir)}/implementations/{script}"
    written: list[Path] = []
    for vendor, name, build in (
        ("claude_code", "pretooluse.json", lambda cmd: hook_entry(cmd, matcher=MATCHER)),
        (
            "cursor",
            "cursor-hooks.json",
            lambda cmd: {vendors.shell_gate_event("cursor"): [cursor_entry(cmd, fail_closed=True)]},
        ),
    ):
        command = hook_command(_adapter_rel(vendor), "--guard", guard)
        dest = output_dir / name
        write_generated_json(dest, build(command))
        written.append(dest)
    for vendor in GENERIC_VENDORS:
        command = hook_command(_adapter_rel(vendor), "--guard", guard)
        dest = output_dir / f"{vendor}-hooks.json"
        write_generated_json(dest, generic_hooks_file(vendor, command))
        written.append(dest)
    return written


def _gate_fragments(policy_id: str, spec: dict[str, Any], output_dir: Path) -> list[Path]:
    """The content fragments, for the vendors whose write vocabulary is actually recorded.

    Most vendors record no `tools.write`, and a pre-tool hook needs a matcher. Inventing one
    would gate a tool name nobody verified the vendor uses, so those vendors get no fragment
    and the coverage they are credited with stays exactly what it was.
    """
    gate = output_dir / GATE_FILE
    write_generated_json(gate, spec)
    written: list[Path] = [gate]

    reference = f"{_compiled_rel(policy_id)}/{GATE_FILE}"
    for vendor in sorted(vendors.in_agent_vendors()):
        matcher = vendors.write_matcher(vendor)
        if matcher is None:
            continue
        command = hook_command(_adapter_rel(vendor), "--gate", reference)
        name = WRITE_FRAGMENT if vendor == "claude_code" else f"{vendor}-write-hooks.json"
        dest = output_dir / name
        if vendors.hook_entry_flat(vendor):
            # A flat entry carries no matcher: the runtime answers every tool under the event
            # and judges only a write it recognises; an unmatched tool is allowed unremarked.
            doc: dict[str, Any] = {vendors.pre_tool_event(vendor): [cursor_entry(command, fail_closed=True)]}
        else:
            doc = hook_entry(command, matcher=matcher)
        write_generated_json(dest, doc)
        written.append(dest)
    return written


#: The claude fragment the stop installer merges, named apart from the two pre-tool ones
#: because it lands under a different event key in the same settings file.
STOP_FRAGMENT = "stop.json"


def _stop_rel(policy_id: str) -> str:
    """Where this policy's stop artifacts land, from chock's own compiled layout."""
    return f".chock/compiled/{policy_id}/stop"


def _stop_fragments(policy_id: str, spec: dict[str, Any], output_dir: Path) -> list[Path]:
    """One fragment per stop vendor, plus the gate they all run.

    Every vendor `stop_vendors` admits gets one. A turn-end hook carries no tool to match
    on, so nothing here depends on a write vocabulary -- the reason this surface reaches
    seven vendors where the write path reaches three.
    """
    gate = output_dir / GATE_FILE
    write_generated_json(gate, spec)
    written: list[Path] = [gate]

    for vendor in vendors.stop_vendors():
        command = hook_command(_adapter_rel(vendor), "--gate", f"{_stop_rel(policy_id)}/{GATE_FILE}")
        if vendor == "claude_code":
            dest, doc = output_dir / STOP_FRAGMENT, hook_entry(command)
        elif vendors.hook_entry_flat(vendor):
            # Cursor's fragment is the event's entry list, the shape its merged installer reads.
            dest, doc = output_dir / f"{vendor}-hooks.json", {vendors.stop_event(vendor): [cursor_entry(command)]}
        else:
            dest, doc = output_dir / f"{vendor}-hooks.json", vendors.stop_hook_config(vendor, command)
        write_generated_json(dest, doc)
        written.append(dest)
    return written


def emit_stop(policy_dir: Path, output_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """Write the end-of-turn fragments for a policy whose gate can judge what a turn wrote.

    Gate-only, deliberately: the shell half of `pre-tool-use` judges a command, and a
    finished turn has none to judge. A policy carrying only a guard script emits nothing
    here rather than a hook that would have nothing to look at.
    """
    policy_id = str(manifest.get("id", policy_dir.name))
    spec = _tool_use_gate(policy_dir, output_dir)
    if spec is None:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    return _stop_fragments(policy_id, spec, output_dir)


def emit_pre_tool_use(policy_dir: Path, output_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """Write the pre-tool-use fragments: a shell guard's, a content gate's, or neither."""
    policy_id = manifest.get("id", policy_dir.name)
    script = _guard_script(policy_dir, policy_id)
    spec = None if script else _tool_use_gate(policy_dir, output_dir)
    if not script and spec is None:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    if script:
        return _guard_fragments(policy_dir, script, output_dir)
    return _gate_fragments(str(policy_id), spec or {}, output_dir)


def build_entry(policy_dir: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
    """The single agent-hooks entry for one policy, or None when it has no guard script."""
    policy_id = manifest.get("id", policy_dir.name)
    script = _guard_script(policy_dir, policy_id)
    if not script:
        return None
    # One string for both keys: the launcher form reads the same under bash and PowerShell.
    command = hook_command(_adapter_rel("vscode_copilot"), "--guard", f"{policy_rel_path(policy_dir)}/implementations/{script}")
    bash = powershell = command
    return {
        "type": "command",
        "matcher": SHELL_MATCHER,
        "timeout": TIMEOUT_SECONDS,
        "timeoutSec": TIMEOUT_SECONDS,
        "bash": bash,
        "command": bash,
        "powershell": powershell,
        "windows": powershell,
    }


def emit_agent_hooks(policy_dir: Path, output_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """Write the per-policy entry; the installer aggregates them into .github/hooks/chock.json."""
    entry = build_entry(policy_dir, manifest)
    if entry is None:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / "agent-hooks.json"
    write_generated_json(dest, entry)
    return [dest]


pre_tool_use = SimpleNamespace(emit=emit_pre_tool_use)
stop = SimpleNamespace(emit=emit_stop)
agent_hooks = SimpleNamespace(emit=emit_agent_hooks)

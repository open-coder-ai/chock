"""The one in-agent emitter: hook fragments for every wired vendor, wire facts from vendor config."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from chock import vendors
from chock.compile.emitters import DATA_DIR
from chock.emit import write_generated_json

_BASH_TEMPLATE = DATA_DIR.joinpath("agent_hook_bash.sh").read_text(encoding="utf-8").rstrip("\n")
_POWERSHELL_TEMPLATE = DATA_DIR.joinpath("agent_hook_powershell.ps1").read_text(encoding="utf-8").rstrip("\n")

GUARD_SCRIPTS = {
    "block-destructive-commands": "block-destructive.sh",
    "block-no-verify": "block-no-verify.sh",
}


def _guard_script(policy_dir: Path, policy_id: str) -> str | None:
    """The policy's guard script name, by convention first, legacy map second."""
    impl = policy_dir / "implementations"
    if (impl / f"{policy_id}.sh").exists():
        return f"{policy_id}.sh"
    legacy = GUARD_SCRIPTS.get(policy_id)
    if legacy and (impl / legacy).exists():
        return legacy
    return None


TIMEOUT_SECONDS = 30

#: claude_code is the only vendor whose shell vocabulary agentseam 0.2.0 records
#: (`tools.shell`); codex_cli and vscode_copilot record none, so their claude-format
#: plugin hooks borrow this matcher exactly as the hand-written emitters did
#: (tests/test_vendor_wire_facts.py trips when upstream closes the gap).
MATCHER = vendors.shell_matcher("claude_code")
assert MATCHER is not None

#: Wire token Claude Code substitutes for the repo root; agentseam 0.2.0's vendor-config
#: schema carries no repo-root-token field yet, so the fact still lives here.
PROJECT_DIR_TOKEN = "${CLAUDE_PROJECT_DIR}"  # noqa: S105 -- a shell variable reference, not a credential

# Witnessed overrides: chock's agent-hooks file speaks `preToolUse` with bash/powershell/
# timeoutSec entry keys (live deny, data/witnesses.json: vscode_copilot x agent-hooks);
# agentseam 0.2.0 records `PreToolUse` with {type, command, windows} instead. The facts
# stay here until upstream ingests the witnessed shape; tests/test_vendor_wire_facts.py
# pins the disagreement so its resolution surfaces loudly.
AGENT_HOOKS_EVENT = "preToolUse"
AGENT_HOOKS_ENVELOPE = {"version": 1}
SHELL_MATCHER = "bash|powershell|pwsh|sh|shell"


def _relative_to_repo(policy_dir: Path) -> str:
    """The policy's path relative to the repo root, derived from the policy, not the output."""
    path = Path(policy_dir).resolve()
    for parent in path.parents:
        if (parent / ".agents").is_dir() or (parent / ".chock").is_dir():
            try:
                return path.relative_to(parent).as_posix()
            except ValueError:  # pragma: no cover - relative_to cannot fail on a parent
                break
    return path.name


def _adapter_rel(vendor: str) -> str:
    """Where the vendored runtime lives in a consumer repo: chock's convention + agent id."""
    return f".chock/bin/{vendor}.py"


#: Vendors wired through hand-shaped fragments that predate the derivation (claude/cursor
#: entry shapes, the witnessed agent-hooks override). Everyone else the membership
#: predicate admits renders through agentseam's own hook_config -- no per-vendor emitter.
BESPOKE_VENDORS = ("claude_code", "cursor", "vscode_copilot")

GENERIC_VENDORS = tuple(v for v in vendors.in_agent_vendors() if v not in BESPOKE_VENDORS)


def generic_hooks_file(vendor: str, command: str) -> dict[str, Any]:
    """`vendor`'s full hook-config document for one guard command, agentseam's rendering.

    Paths inside `command` are repo-relative: no repo-root token is recorded upstream for
    these vendors (the `${CLAUDE_PROJECT_DIR}` gap), so the entry resolves only where the
    vendor runs hooks from the repo root -- the same condition under which the relative
    adapter path resolves at all.
    """
    return vendors.pre_tool_hook_config(vendor, command, matcher=vendors.shell_matcher(vendor))


def hook_entry(command: str, *, matcher: str | None = None) -> dict[str, Any]:
    """One hooks-map entry (agentseam's `hooks_map` wrapper shape) plus chock's timeout."""
    entry: dict[str, Any] = {}
    if matcher is not None:
        entry["matcher"] = matcher
    entry["hooks"] = [{"type": "command", "command": command, "timeout": TIMEOUT_SECONDS}]
    return entry


def hooks_map_file(vendor: str, command: str) -> dict[str, Any]:
    """A claude-plugin-format hooks file under `vendor`'s own pre-tool event spelling."""
    return {"hooks": {vendors.pre_tool_event(vendor): [hook_entry(command, matcher=MATCHER)]}}


def cursor_entry(command: str) -> dict[str, Any]:
    """One cursor hook entry: the flat `cursor` wrapper shape plus chock's timeout."""
    return {"command": command, "timeout": TIMEOUT_SECONDS}


def cursor_hooks_file(command: str) -> dict[str, Any]:
    """A cursor-format hooks file: envelope and shell-gate event from the vendor entry."""
    return {
        **vendors.config_envelope("cursor"),
        "hooks": {vendors.shell_gate_event("cursor"): [cursor_entry(command)]},
    }


def emit_pre_tool_use(policy_dir: Path, output_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """Write the pre-tool-use fragments (Claude Code entry shape, cursor entry shape)."""
    policy_id = manifest.get("id", policy_dir.name)
    script = _guard_script(policy_dir, policy_id)
    if not script:
        return []

    rel = _relative_to_repo(policy_dir)
    guard = f"{PROJECT_DIR_TOKEN}/{rel}/implementations/{script}"

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for vendor, name, build in (
        ("claude_code", "pretooluse.json", lambda cmd: hook_entry(cmd, matcher=MATCHER)),
        ("cursor", "cursor-hooks.json", lambda cmd: {vendors.shell_gate_event("cursor"): [cursor_entry(cmd)]}),
    ):
        adapter = f"{PROJECT_DIR_TOKEN}/{_adapter_rel(vendor)}"
        command = f'@CHOCK_PYTHON@ "{adapter}" --guard "{guard}"'
        dest = output_dir / name
        write_generated_json(dest, build(command))
        written.append(dest)
    for vendor in GENERIC_VENDORS:
        command = f'@CHOCK_PYTHON@ "{_adapter_rel(vendor)}" --guard "{rel}/implementations/{script}"'
        dest = output_dir / f"{vendor}-hooks.json"
        write_generated_json(dest, generic_hooks_file(vendor, command))
        written.append(dest)
    return written


def _bash_command(adapter: str, guard: str) -> str:
    return _BASH_TEMPLATE.replace("__ADAPTER__", adapter).replace("__GUARD__", guard)


def _powershell_command(adapter: str, guard: str) -> str:
    return _POWERSHELL_TEMPLATE.replace("__ADAPTER__", adapter).replace("__GUARD__", guard)


def build_entry(policy_dir: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
    """The single agent-hooks entry for one policy, or None when it has no guard script."""
    policy_id = manifest.get("id", policy_dir.name)
    script = _guard_script(policy_dir, policy_id)
    if not script:
        return None
    rel = _relative_to_repo(policy_dir)
    adapter = _adapter_rel("vscode_copilot")
    guard = f"{rel}/implementations/{script}"
    bash = _bash_command(adapter, guard)
    powershell = _powershell_command(adapter, guard)
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
agent_hooks = SimpleNamespace(emit=emit_agent_hooks)

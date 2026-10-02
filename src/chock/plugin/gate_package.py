"""A policy's gate as a plugin carries it: what travels, where it runs, and what the package may claim.

Shared by every hook-carrying store. A plugin installs at the agent, not in a repository, so
the compiled gate, the stdlib runner and a script gate's program travel together under the
package's `scripts/`, and the bundled runtime finds the runner beside the gate. What the gate
reaches in a client is agentseam's answer, never typed here: the write path where the vendor
records a write-tool vocabulary, the turn's end where it records a blocking stop hook.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentseam import contract, matrix

from chock import vendors
from chock.compile.emitters.in_agent import GATE_FILE
from chock.compile.emitters.in_agent_hooks import cursor_entry, hook_entry
from chock.gate import assemble
from chock.gate.runner import SCRIPT_BASE_GATE
from chock.gate.write_gate import STOP_FLAG

RUNNER_FILE = "gate.py"
IMPLEMENTATIONS = "implementations"

_STOP_ONLY_POSTURE = (
    "Session-enforced at the turn's end by a Stop hook; needs git and a Python 3.11+. This client records no "
    "file-writing tool vocabulary, so the write itself is not judged: what the turn actually left "
    "on disk is re-read, and a construct a rule denies is refused then, however it was written. "
    "With no working Python the hook exits 2; without git, fail-open clients allow silently. "
    "A gate that cannot reach a decision "
    "refuses rather than allowing one it never judged. Enforcement at every commit and in CI "
    "still needs chock installed in the repo."
)
_WRITE_AND_STOP_POSTURE = (
    "Session-enforced via PreToolUse and Stop hooks; needs git and a Python 3.11+. PreToolUse "
    "judges the file "
    "a tool call would write; Stop re-reads what the turn actually left on disk, so a file "
    "written through a shell heredoc is judged too. With no working Python the hook exits 2; "
    "without git, fail-open clients allow silently. A gate that cannot reach a decision refuses rather than allowing one it never "
    "judged. Enforcement at every commit and in CI still needs chock installed in the repo."
)
_STOP_ONLY_NOTE = (
    "This policy __LEAD__ the Stop hook installed with the plugin: the "
    "write itself is not judged here, because the client records no write-tool vocabulary, "
    "and what the turn left on disk is judged at its end instead. Subject to the fail "
    "conditions stated in the plugin description. Repo-wide enforcement across every commit "
    "and in CI still needs `chock sync`. See https://github.com/open-coder-ai/chock"
)
_WRITE_AND_STOP_NOTE = (
    "This policy __LEAD__ the PreToolUse and Stop hooks installed with "
    "the plugin, subject to the fail conditions stated in the plugin description. Repo-wide "
    "enforcement across every commit and in CI still needs `chock sync`. "
    "See https://github.com/open-coder-ai/chock"
)
_ACTION_LEAD = {
    "block": "is enforced in this client by",
    "ask": "asks the person before the action proceeds, through",
    "warn": "warns, and does not block, through",
}


def gate_reach(vendor: str) -> tuple[str | None, bool]:
    """(the write matcher, whether the turn's end blocks) for `vendor`, from agentseam's records."""
    return vendors.write_matcher(vendor), matrix.can_block(vendor, contract.STOP)


def gate_reaches(vendor: str) -> bool:
    """Whether a packaged gate has any surface at all in `vendor`; without one, no hook is installed."""
    matcher, stop = gate_reach(vendor)
    return matcher is not None or stop


def gate_hooks_file(vendor: str, command: str) -> dict[str, Any]:
    """The hooks document running `command` on every surface the gate reaches in `vendor`."""
    matcher, stop = gate_reach(vendor)
    flat = vendors.hook_entry_flat(vendor)
    entries: dict[str, list[dict[str, Any]]] = {}
    if matcher is not None:
        # A flat entry carries no matcher: the runtime answers every tool and judges only a
        # write it recognises, so an unmatched tool is allowed with nothing said.
        entries[vendors.pre_tool_event(vendor)] = [
            cursor_entry(command, fail_closed=True) if flat else hook_entry(command, matcher=matcher)
        ]
    if stop:
        # The Stop hook shares the pre-tool gate file, so it says which event it serves: an unreadable
        # Stop payload then earns the vendor's Stop refusal, not the pre-tool grammar.
        stop_command = f"{command} {STOP_FLAG}"
        entries[vendors.stop_event(vendor)] = [cursor_entry(stop_command) if flat else hook_entry(stop_command)]
    if flat:
        return {**vendors.config_envelope(vendor), "hooks": entries}
    return entries if vendors.hook_entry_bare(vendor) else {"hooks": entries}


def gate_posture(vendor: str, caveat: str = "") -> str:
    """The package's own statement of what its gate reaches in `vendor`, plus the vendor's caveat."""
    matcher, _ = gate_reach(vendor)
    text = _WRITE_AND_STOP_POSTURE if matcher is not None else _STOP_ONLY_POSTURE
    return f"{text} {caveat}".strip()


def gate_skill_note(vendor: str, action: str | None = None) -> str:
    """The note the packaged skill ends with when it carries a gate: block unless the gate asks or warns."""
    matcher, _ = gate_reach(vendor)
    note = _WRITE_AND_STOP_NOTE if matcher is not None else _STOP_ONLY_NOTE
    return note.replace("__LEAD__", _ACTION_LEAD.get(action or "block", _ACTION_LEAD["block"]))


def runner_source() -> str:
    """The stdlib-only gate runner, assembled byte for byte as `chock sync` vendors it under .chock/bin."""
    return assemble.runner_source()


def packaged_gate_files(policy_dir: Path, spec: dict[str, Any], scripts_template: str) -> dict[Path, str]:
    """The gate, the runner beside it, and a script gate's program with the files it imports.

    Keyed by path inside the package. A script gate's `implementations/` is copied whole, so
    a program that puts its own directory on `sys.path` still finds what it imports, and the
    gate says `script_base: gate` so the runner resolves the script beside the gate file
    rather than under a repository root the plugin does not have.
    """
    packaged = {key: value for key, value in spec.items() if key != "params"}
    packaged["params"] = dict(spec.get("params") or {})
    files: dict[Path, str] = {Path(scripts_template.format(name=RUNNER_FILE)): runner_source()}
    if spec.get("kind") == "script":
        name = Path(str(packaged["params"].get("script", ""))).name
        packaged["params"]["script"] = f"{IMPLEMENTATIONS}/{name}"
        packaged["script_base"] = SCRIPT_BASE_GATE
        root = Path(policy_dir) / IMPLEMENTATIONS
        for path in sorted(root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                rel = Path(IMPLEMENTATIONS) / path.relative_to(root)
                files[Path(scripts_template.format(name=rel.as_posix()))] = path.read_text(encoding="utf-8")
    files[Path(scripts_template.format(name=GATE_FILE))] = json.dumps(packaged, indent=2) + "\n"
    return files

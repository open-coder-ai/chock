"""Emit git-hook event entrypoints from a policy's implementations directory."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from chock.compile.emitters import DATA_DIR, GUARD_SUFFIXES, SCRIPT_EVENTS, policy_rel_path
from chock.compile.emitters.advisory import repo_root_from_output, template_message
from chock.emit import write_generated, write_generated_json
from chock.gate.build import build_gate_json, vendor_runner

SHIM_TEMPLATE = DATA_DIR.joinpath("git_hook_shim.sh").read_text(encoding="utf-8")
SCRIPT_SHIM_TEMPLATE = DATA_DIR.joinpath("git_hook_script_shim.sh").read_text(encoding="utf-8")


def _emit_shims(output_dir: Path, policy_id: str, events: list[str]) -> list[Path]:
    emitted: list[Path] = []
    for event in events:
        if event == "commit":
            script_name = "git-pre-commit.sh"
            event_arg = "pre-commit"
        elif event == "push":
            script_name = "git-pre-push.sh"
            event_arg = "pre-push"
        else:
            continue
        shim = output_dir / script_name
        rendered = SHIM_TEMPLATE.replace("__POLICY_ID__", policy_id).replace("__EVENT__", event_arg)
        write_generated(shim, rendered)
        with contextlib.suppress(OSError):
            shim.chmod(0o755)
        emitted.append(shim)
    return emitted


def _script_name(policy_dir: Path, policy_id: str, segment: str) -> str | None:
    """The file the hook would run for `segment`, or None when the policy ships none."""
    impl = policy_dir / "implementations"
    for suffix in GUARD_SUFFIXES:
        name = f"{policy_id}-{segment}{suffix}"
        if (impl / name).exists():
            return name
    return None


def declared_script_events(manifest: dict[str, Any]) -> list[str]:
    """The events `hook.script` declares. This list is what gets wired, not what is on disk."""
    declared = ((manifest.get("hook") or {}).get("script") or {}).get("on") or []
    return [event for event in SCRIPT_EVENTS if event in declared]


def _emit_script_shims(policy_dir: Path, output_dir: Path, policy_id: str, events: list[str]) -> list[Path]:
    """Emit one shim per declared event. The guard reads the change from git itself."""
    rel = policy_rel_path(policy_dir)
    emitted: list[Path] = []
    for event in events:
        segment = SCRIPT_EVENTS[event]
        # A declared event with no script on disk is a validation error, not a shim that
        # fails at commit time in someone else's repo.
        if (script := _script_name(policy_dir, policy_id, segment)) is None:
            continue
        shim = output_dir / f"git-{segment}.sh"
        rendered = SCRIPT_SHIM_TEMPLATE.replace("__POLICY_ID__", policy_id).replace(
            "__GUARD_REL__", f"{rel}/implementations/{script}"
        )
        write_generated(shim, rendered)
        with contextlib.suppress(OSError):
            shim.chmod(0o755)
        emitted.append(shim)
    return emitted


def emit(policy_dir: Path, output_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """Emit git hooks from the manifest hook.gate as gate.json + shims."""
    policy_dir = Path(policy_dir).resolve()
    output_dir = Path(output_dir).resolve()
    policy_id = manifest.get("id") or policy_dir.name

    repo_root = repo_root_from_output(output_dir)
    spec = build_gate_json(policy_dir, repo_root)
    if spec is None:
        # No declarative gate. A policy whose check needs more than a regex over the diff
        # ships its own script and declares the events it runs at; the shim runs that.
        return _emit_script_shims(policy_dir, output_dir, policy_id, declared_script_events(manifest))

    hook_events = [e for e in spec.get("on", []) if e in ("commit", "push")]
    if not hook_events:
        return []

    spec["message"] = template_message(spec["message"], spec["params"])

    gate_json = output_dir / "gate.json"
    write_generated_json(gate_json, spec)
    emitted: list[Path] = [gate_json]

    emitted.append(vendor_runner(output_dir.parents[2]))
    emitted.extend(_emit_shims(output_dir, policy_id, hook_events))
    return emitted

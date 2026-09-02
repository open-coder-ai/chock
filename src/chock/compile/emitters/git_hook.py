"""Emit git-hook event entrypoints from a policy's implementations directory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.compile.emitters.advisory import repo_root_from_output, template_message
from chock.emit import write_generated, write_generated_json
from chock.gate.build import build_gate_json, vendor_runner
from chock.resources import render_template


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
        write_generated(shim, render_template("git-hook/shim.sh", {"__POLICY_ID__": policy_id, "__EVENT__": event_arg}))
        try:
            shim.chmod(0o755)
        except OSError:
            pass
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
        return []

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

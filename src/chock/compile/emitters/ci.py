"""Emit a CI gate step that re-runs the policy guard over a PR's commit range."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.compile.emitters.advisory import repo_root_from_output, template_message
from chock.emit import write_generated, write_generated_json
from chock.gate.build import build_gate_json, vendor_runner
from chock.resources import render_template


def emit(policy_dir: Path, output_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """Write a resolved gate.json plus a runnable CI step for it."""
    policy_dir = Path(policy_dir).resolve()
    output_dir = Path(output_dir).resolve()
    policy_id = manifest.get("id") or policy_dir.name
    repo_root = repo_root_from_output(output_dir)

    spec = build_gate_json(policy_dir, repo_root)
    if spec is None or "commit" not in spec.get("on", []):
        return []
    spec["message"] = template_message(spec["message"], spec["params"])

    gate_json = output_dir / "gate.json"
    write_generated_json(gate_json, spec)

    emitted = [gate_json, vendor_runner(output_dir.parents[2])]

    gate_path = f".chock/compiled/{policy_id}/ci-gate/gate.json"
    step = output_dir / "step.yaml"
    write_generated(step, render_template("ci/step.yaml", {"__POLICY_ID__": policy_id, "__GATE_PATH__": gate_path}))
    emitted.append(step)
    return emitted

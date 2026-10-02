"""Authoring-side gate compiler: manifest hook.gate -> resolved gate.json."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from chock.compile.emitters import policy_rel_path
from chock.config import load_config
from chock.emit import write_generated
from chock.gate.assemble import runner_source
from chock.manifest import load_manifest


def _resolve_dotted(config: dict[str, Any], key: str) -> Any:
    """Resolve a dot-separated key like 'chock.defaults.refs'."""
    value = config
    for part in key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def build_gate_json(policy_dir: Path, repo_root: Path) -> dict[str, Any] | None:
    """Load a manifest hook.gate, resolve config references, and return a flat gate.json dict."""
    result = load_manifest(policy_dir)
    if result is None:
        return None
    manifest, _ = result

    gate = (manifest.get("hook") or {}).get("gate")
    if not isinstance(gate, dict) or not gate.get("kind"):
        return None

    spec: dict[str, Any] = {
        "kind": gate["kind"],
        "on": list(gate.get("on", [])),
        "action": gate.get("action", "block"),
        "message": str(gate.get("message", "")).strip(),
        "params": dict(gate.get("params") or {}),
    }

    # applies_to.paths bounds which files this gate may judge. It rides beside params rather
    # than inside them: params are what the policy declared about its check, and this is what
    # the policy declared about its reach.
    scope = (manifest.get("applies_to") or {}).get("paths")
    if scope:
        spec["paths"] = [str(p) for p in scope]

    outside = gate.get("outside_repo")
    if outside:
        spec["outside_repo"] = [str(g) for g in outside]

    config = load_config(repo_root)

    if "config_key" in spec["params"]:
        resolved = _resolve_dotted(config, spec["params"]["config_key"])
        if isinstance(resolved, list) and resolved:
            spec["params"]["refs"] = [str(r) for r in resolved]
        spec["params"].pop("config_key", None)

    if spec["kind"] == "script":
        # The manifest names a file under the policy's own implementations/. The compiled gate
        # carries where that is from the repository root, which is all the runner has to go on.
        script = str(spec["params"].get("script", ""))
        spec["params"]["script"] = f"{policy_rel_path(policy_dir)}/implementations/{script}"

    return spec


def vendor_runner(artifact_root: Path) -> Path:
    """Write the stdlib-only runner, assembled from chock.gate.runner, to `<artifact_root>/bin/gate.py`."""
    dest = Path(artifact_root) / "bin" / "gate.py"
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_generated(dest, runner_source())
    with contextlib.suppress(OSError):
        dest.chmod(0o755)
    return dest

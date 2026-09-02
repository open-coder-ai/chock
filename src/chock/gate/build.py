"""Authoring-side gate compiler: manifest hook.gate -> resolved gate.json."""

from __future__ import annotations

import contextlib
import shutil
from pathlib import Path
from typing import Any

from chock.config import load_config
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

    config = load_config(repo_root)

    if "config_key" in spec["params"]:
        resolved = _resolve_dotted(config, spec["params"]["config_key"])
        if isinstance(resolved, list) and resolved:
            spec["params"]["refs"] = [str(r) for r in resolved]
        spec["params"].pop("config_key", None)

    return spec


def vendor_runner(artifact_root: Path) -> Path:
    """Copy the stdlib-only runner into `<artifact_root>/bin/gate.py`."""
    source = Path(__file__).resolve().parent / "runner.py"
    if not source.exists():
        msg = (
            f"Vendored gate runner source not found at {source}. "
            "If this is a packaged binary, ensure gate/runner.py is bundled as a data file."
        )
        raise FileNotFoundError(msg)
    dest = Path(artifact_root) / "bin" / "gate.py"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    with contextlib.suppress(OSError):
        dest.chmod(0o755)
    return dest

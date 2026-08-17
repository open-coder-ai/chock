"""Authoring-side gate compiler: manifest hook.gate -> resolved gate.json."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from chock.config import load_config


def _resolve_dotted(config: dict[str, Any], key: str) -> Any:
    """Resolve a dot-separated key like 'chock.defaults.refs'."""
    value = config
    for part in key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def build_gate_json(policy_dir: Path, repo_root: Path) -> dict[str, Any] | None:
    """Load a manifest hook.gate, resolve config references, and return a flat gate.json dict.

    Returns None if the policy has no declarative hook.gate.
    """
    from chock.manifest import load_manifest

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
    """Copy the stdlib-only runner into `<artifact_root>/bin/gate.py`.

    `artifact_root` is the `.chock` directory that owns the compiled tree being
    written -- the same root `coverage.json` goes to -- and is passed in, never inferred
    from the repo. It used to take a repo root resolved by walking up from the output
    directory, which fell through to `git rev-parse` in the current working directory when
    compiling into a temp tree. `recompile --check` does exactly that, so a read-only check
    wrote into the working tree it was measuring: it silently restored a tampered
    `.chock/bin/gate.py` and reported no difference.
    """
    source = Path(__file__).resolve().parent / "runner.py"
    if not source.exists():
        # In a frozen (PyInstaller) build, .py modules are bytecode inside the binary and are
        # not extracted as files. runner.py must be shipped as DATA — see packaging/chock.spec.
        raise FileNotFoundError(
            f"Vendored gate runner source not found at {source}. "
            "If this is a packaged binary, ensure gate/runner.py is bundled as a data file."
        )
    dest = Path(artifact_root) / "bin" / "gate.py"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    try:
        dest.chmod(0o755)
    except OSError:
        pass  # best-effort: chmod is a no-op/denied on Windows; the gate is invoked as `python <path>`
    return dest

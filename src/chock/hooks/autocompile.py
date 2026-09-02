"""Compile drop-in policies that have a gate but no compiled output yet."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from chock.compile.surfaces import Surface
from chock.config import agents_from_config, load_config, policy_status
from chock.policies import discover_policy_dirs


def compile_one_dropin(
    pack_dir: Path,
    config: dict,
    compiled_root: Path,
    agents: list[str] | None = None,
    repo_root: Path | None = None,
) -> bool:
    """Compile a single drop-in policy's git-hook output. Returns True if it compiled."""
    mf_path = pack_dir / "manifest.yaml"
    if not mf_path.exists():
        return False
    manifest = yaml.safe_load(mf_path.read_text(encoding="utf-8")) or {}

    if manifest.get("artifact") != "hook":
        return False

    policy_id = manifest.get("id") or pack_dir.name
    status = policy_status(config, policy_id, manifest)
    if status["state"] == "disabled":
        return False

    if Surface.GIT_HOOK.value not in status.get("targets", []):
        return False

    expected = compiled_root / policy_id / "git-hook"
    if expected.is_dir() and any(expected.iterdir()):
        return False

    # Tests patch chock.compile.compiler.compile_policy directly (test_engine_scan.py,
    # test_agent_selection.py), which only takes effect on a fresh per-call lookup.
    from chock.compile.compiler import compile_policy  # noqa: PLC0415

    compile_policy(
        pack_dir,
        targets=[Surface.GIT_HOOK.value],
        output_root=compiled_root,
        agents=agents,
        repo_root=repo_root,
    )
    print(f"Auto-compiled {policy_id} (drop-in)")
    return True


def auto_compile(repo_root: Path) -> None:
    """Compile any policy that has a hook gate but no compiled git-hook output yet."""
    try:
        config = load_config(repo_root)
        agents = agents_from_config(repo_root)
        pack_dirs = discover_policy_dirs(repo_root)
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] auto-compile could not enumerate policies: {exc}", file=sys.stderr)
        return

    compiled_root = repo_root / ".chock" / "compiled"
    for pack_dir in pack_dirs:
        try:
            compile_one_dropin(pack_dir, config, compiled_root, agents=agents, repo_root=repo_root)
        except Exception as exc:  # noqa: BLE001
            print(
                f"[WARN] skipped policy '{pack_dir.name}': {exc}. Other policies still compiled.",
                file=sys.stderr,
            )

"""Compile drop-in policies that have a gate but no compiled output yet.

Split out of `install.py` when that file outgrew the 300-line review budget. This is a
distinct activity from installing hooks: it turns policy folders into compiled artifacts,
and the installer then wires whatever it finds.
"""

from __future__ import annotations

import sys
from pathlib import Path


def compile_one_dropin(
    pack_dir: Path,
    config: dict,
    compiled_root: Path,
    agents: list[str] | None = None,
    repo_root: Path | None = None,
) -> bool:
    """Compile a single drop-in policy's git-hook output. Returns True if it compiled.

    Raises nothing the caller must handle beyond logging: every failure mode here is
    scoped to this one policy so a bad folder cannot affect any other.
    """
    import yaml

    from chock.compile.compiler import compile_policy
    from chock.compile.surfaces import Surface
    from chock.config import policy_status

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

    # Only compile if the git-hook output is missing (incremental, not rebuild).
    expected = compiled_root / policy_id / "git-hook"
    if expected.is_dir() and any(expected.iterdir()):
        return False

    # Pass the repo's configured agent set, not the library default. Without it, compile
    # credited coverage for all 13 agents, so a drop-in in a repo pinned to a smaller trio
    # went straight into the drift that `sync --check` then fails -- the CLI was fixed for
    # this, but auto-compile reaches compile_policy without going through the CLI.
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
    """Compile any policy that has a hook gate but no compiled git-hook output yet.

    This is an incremental step, not a full rebuild: it does not touch already-compiled
    policies and never clears the compiled directory. The goal is to enforce drop-in
    policy folders without requiring a manual `chock sync` step.

    Failure is isolated PER POLICY. A malformed or unbuildable folder -- including a
    third-party drop-in -- must never prevent the remaining policies from compiling,
    because those remaining policies include the mandatory guards (protect-main-branch,
    scan-secrets). A shared try/except around the loop would let one bad folder silently
    disable enforcement repo-wide while the installer still reported success.
    """
    try:
        from chock.config import agents_from_config, load_config
        from chock.policies import discover_policy_dirs

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

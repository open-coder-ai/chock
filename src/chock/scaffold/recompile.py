"""Recompile installed policies from config, refreshing compiled artifacts and hooks."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from chock.compile.compiler import _load_manifest, compile_policy
from chock.compile.levels import DISABLED, Grade
from chock.config import agents_from_config, load_config, policy_status
from chock.emit import write_generated_json
from chock.hooks.in_agent_install import WIRED_VENDORS, install_hooks, install_label, installed_policy_ids
from chock.hooks.installers import get_hooks_dir, install_policy_hooks
from chock.hooks.sessionstart_install import install_sessionstart_hook
from chock.index.cli import cmd_refresh
from chock.policies import discover_policy_dirs
from chock.registry.core import save_registry, scan
from chock.vendored import vendored_differences


class BookkeepingError(RuntimeError):
    """Bookkeeping the attestation chain depends on failed after a successful compile."""


def _compile_all(repo_root: Path, agents: list[str], compiled_root: Path) -> dict[str, dict[str, dict[str, object]]]:
    """Compile every enabled policy into `compiled_root`. Returns the coverage map."""
    config = load_config(repo_root)
    coverage: dict[str, dict[str, dict[str, object]]] = {}

    for pack_dir in discover_policy_dirs(repo_root):
        manifest = _load_manifest(pack_dir)
        policy_id = manifest.get("id") or pack_dir.name
        status = policy_status(config, policy_id, manifest)

        if status["state"] == "disabled":
            coverage[policy_id] = {agent: Grade(DISABLED, None, witnessed=False)._asdict() for agent in agents}
            continue

        result = compile_policy(
            pack_dir,
            targets=status["targets"],
            output_root=compiled_root,
            agents=agents,
            repo_root=repo_root,
        )
        if result.coverage.get(policy_id):
            coverage[policy_id] = result.coverage[policy_id]

    return coverage


def compiled_differences(repo_root: Path | str, agents: list[str]) -> list[str]:
    """Every way the committed compiled tree differs from what the manifests produce now."""
    repo_root = Path(repo_root)
    actual_root = repo_root / ".chock" / "compiled"
    diffs: list[str] = []

    with tempfile.TemporaryDirectory(prefix="chock-compilecheck-") as tmp:
        expected_root = Path(tmp) / "compiled"
        expected_root.mkdir(parents=True)
        expected_coverage = _compile_all(repo_root, agents, expected_root)

        expected = {p.relative_to(expected_root) for p in expected_root.rglob("*") if p.is_file()}
        actual = (
            {p.relative_to(actual_root) for p in actual_root.rglob("*") if p.is_file()}
            if actual_root.exists()
            else set()
        )

        diffs += [f"missing: {rel.as_posix()}" for rel in sorted(expected - actual)]
        diffs += [f"stale: {rel.as_posix()}" for rel in sorted(actual - expected)]
        diffs += [
            f"differs: {rel.as_posix()}"
            for rel in sorted(expected & actual)
            if (expected_root / rel).read_bytes() != (actual_root / rel).read_bytes()
        ]

    diffs += vendored_differences(repo_root)

    coverage_path = repo_root / ".chock" / "coverage.json"
    committed = json.loads(coverage_path.read_text(encoding="utf-8")) if coverage_path.exists() else {}
    if committed != expected_coverage:
        diffs.append("differs: coverage.json")

    return diffs


def _refresh_bookkeeping(repo_root: Path) -> None:
    """Bring the index and the registry back in line with the policies on disk."""
    try:
        entries, _skips = scan(repo_root)
        save_registry(entries, repo_root)
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] registry scan failed: {exc}. Run `chock registry scan`.", file=sys.stderr)

    try:
        cmd_refresh(["--repo", str(repo_root)])
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] index refresh failed: {exc}. Run `chock sync`.", file=sys.stderr)

    try:
        # Tests patch chock.lock.write_lock/build_lock directly (test_adopter_safety.py),
        # which only takes effect on a fresh per-call lookup.
        from chock.lock import build_lock, write_lock  # noqa: PLC0415

        write_lock(build_lock(repo_root), repo_root)
    except Exception as exc:
        msg = (
            f"chock.lock was not updated ({exc}). The compiled artifacts are in place, but the "
            "lockfile still attests the previous ones -- `chock check --only verify` will fail "
            "until a `chock sync --repo .` succeeds."
        )
        raise BookkeepingError(msg) from exc


def refresh_after_install(repo_root: Path) -> None:
    """Recompile so coverage reflects the settings.json an install just wrote."""
    try:
        recompile(repo_root, agents_from_config(repo_root), skip_hooks=True)
    except Exception as exc:  # noqa: BLE001 - never fail an install over bookkeeping
        print(f"[WARN] coverage not refreshed: {exc}. Run `chock sync --repo .`", file=sys.stderr)


def recompile(repo_root: Path | str, agents: list[str], *, skip_hooks: bool = False) -> dict[str, Any]:
    """Compile all enabled policies from a clean compiled/ directory and install hooks."""
    repo_root = Path(repo_root)
    chock_dir = repo_root / ".chock"
    compiled_root = chock_dir / "compiled"
    coverage_path = chock_dir / "coverage.json"

    chock_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="chock-recompile-", dir=chock_dir) as tmp:
        staged_chock = Path(tmp)
        staged_compiled = staged_chock / "compiled"
        staged_compiled.mkdir(parents=True)

        coverage = _compile_all(repo_root, agents, staged_compiled)

        if compiled_root.exists():
            shutil.rmtree(compiled_root)
        shutil.move(str(staged_compiled), str(compiled_root))
        staged_runner = staged_chock / "bin" / "gate.py"
        if staged_runner.exists():
            (chock_dir / "bin").mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(staged_runner), str(chock_dir / "bin" / "gate.py"))

    write_generated_json(coverage_path, coverage)

    if not skip_hooks:
        install_policy_hooks(repo_root, get_hooks_dir(repo_root))

        try:
            if install_sessionstart_hook(repo_root):
                print("Registered SessionStart arm hook in .claude/settings.json")
        except ValueError as exc:
            print(f"[WARN] {exc}", file=sys.stderr)

        def _witness() -> tuple[set[str], ...]:
            return tuple(installed_policy_ids(repo_root, vendor) for vendor in WIRED_VENDORS)

        before = _witness()
        for vendor in WIRED_VENDORS:
            try:
                installed = install_hooks(repo_root, vendor)
            except ValueError as exc:
                print(f"[WARN] {exc}", file=sys.stderr)
            else:
                if installed:
                    print(f"Registered {len(installed)} {install_label(vendor)}")
        if _witness() != before:
            with tempfile.TemporaryDirectory(prefix="chock-coverage-", dir=chock_dir) as tmp2:
                coverage = _compile_all(repo_root, agents, Path(tmp2) / "compiled")
            write_generated_json(coverage_path, coverage)

    _refresh_bookkeeping(repo_root)

    return coverage

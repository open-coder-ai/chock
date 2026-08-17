"""Policy table, enable/disable toggles, and the full recompile command.

Moved out of `cli.py` when the CLI grew umbrella commands (`sync`, `status`) that
need these implementations: the dispatcher stays a dispatcher, and the import
direction stays one-way (cli -> lifecycle -> here -> scaffold).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from chock.config import agents_from_config as _agents_from_config
from chock.config import load_config, policy_status, set_disabled
from chock.manifest import ManifestSourceError, load_manifest
from chock.policies import discover_policy_dirs
from chock.scaffold.adapters import parse_agent_selection
from chock.scaffold.recompile import BookkeepingError, recompile


def _load_manifest(pack_dir: Path) -> dict[str, Any]:
    warnings: list[str] = []
    try:
        result = load_manifest(pack_dir, warnings=warnings)
    except (yaml.YAMLError, OSError, ManifestSourceError) as exc:
        print(f"[ERROR] {pack_dir / 'manifest.yaml'}: manifest_parse: {exc}", file=sys.stderr)
        return {}
    if result is None:
        return {}
    data, _ = result
    for warning in warnings:
        print(f"[WARN] {pack_dir}: manifest_default: {warning}", file=sys.stderr)
    return data


def _find_policy_manifest(repo_root: Path, policy_id: str) -> dict | None:
    for pack_dir in discover_policy_dirs(repo_root):
        manifest = _load_manifest(pack_dir)
        if manifest.get("id") == policy_id or pack_dir.name == policy_id:
            return manifest
    return None


def _policy_ids(repo_root: Path) -> list[str]:
    ids: list[str] = []
    for pack_dir in discover_policy_dirs(repo_root):
        manifest = _load_manifest(pack_dir)
        ids.append(manifest.get("id") or pack_dir.name)
    return ids


def disable_main(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(prog="chock disable")
    parser.add_argument("policy_id", help="Policy identifier to disable")
    parser.add_argument("--repo", default=".", help="Repo root")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    manifest = _find_policy_manifest(repo_root, args.policy_id)
    if manifest is None:
        print(f"Unknown policy: {args.policy_id}", file=sys.stderr)
        return 2
    if manifest.get("mandatory"):
        print(f"Cannot disable mandatory policy: {args.policy_id}", file=sys.stderr)
        return 2

    try:
        agents = _agents_from_config(repo_root)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    set_disabled(repo_root, args.policy_id, True)
    try:
        recompile(repo_root, agents)
    except BookkeepingError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    from chock.index.cli import cmd_refresh

    cmd_refresh(["--repo", str(repo_root)])
    print(f"Disabled {args.policy_id}")
    return 0


def enable_main(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(prog="chock enable")
    parser.add_argument("policy_id", help="Policy identifier to enable")
    parser.add_argument("--repo", default=".", help="Repo root")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    # Symmetry with `disable`, which already rejects unknown ids. Without this, a typo
    # printed "Enabled <typo>" and changed nothing -- a false success on the command whose
    # whole purpose is turning enforcement on.
    if _find_policy_manifest(repo_root, args.policy_id) is None:
        print(f"Unknown policy: {args.policy_id}", file=sys.stderr)
        return 2

    try:
        agents = _agents_from_config(repo_root)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    set_disabled(repo_root, args.policy_id, False)
    try:
        recompile(repo_root, agents)
    except BookkeepingError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    from chock.index.cli import cmd_refresh

    cmd_refresh(["--repo", str(repo_root)])
    print(f"Enabled {args.policy_id}")
    return 0


def policies_main(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(prog="chock status")
    parser.add_argument("--repo", default=".", help="Repo root")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    config = load_config(repo_root)
    coverage_path = repo_root / ".chock" / "coverage.json"
    coverage: dict[str, dict[str, str]] = {}
    if coverage_path.exists():
        try:
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            coverage = {}

    rows: list[tuple[str, str, str, str]] = []
    for policy_id in sorted(_policy_ids(repo_root)):
        manifest = _find_policy_manifest(repo_root, policy_id)
        status = policy_status(config, policy_id, manifest)
        cov = coverage.get(policy_id, {})
        if not cov:
            cov_str = "none"
        elif all(v == list(cov.values())[0] for v in cov.values()):
            cov_str = list(cov.values())[0]
        else:
            cov_str = "; ".join(f"{a}: {v}" for a, v in sorted(cov.items()))
        rows.append((policy_id, status["state"], cov_str, "yes" if status["mandatory"] else "no"))

    # A bare header row over no rows reads as "nothing to report" when the fact being
    # reported is that this repo enforces nothing at all. The framework ships no policies,
    # so an empty table is the normal state of a freshly scaffolded repo, not an anomaly.
    if not rows:
        print("No policies installed. This repo enforces nothing.")
        print("Copy a policy folder into .agents/policies/<id>/ and run `chock sync --repo .`.")
        return 0

    # Widths come from the data. Fixed widths silently broke the alignment for any id
    # longer than the guess -- `block-destructive-commands` is 26 characters against a 24
    # character column, so every row after it was misaligned in a table adopters read.
    headers = ("id", "state", "coverage", "mandatory")
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)).rstrip())
    for row in rows:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip())
    return 0


def recompile_main(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(prog="chock sync")
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument(
        "--agents",
        nargs="*",
        default=None,
        help="Comma- or space-separated target agents (default: supported_agents from config)",
    )
    parser.add_argument("--skip-hooks", action="store_true", help="Skip reinstalling git hooks")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report compiled artifacts that no longer match their manifests, and exit non-zero. Writes nothing.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    if args.agents is None:
        try:
            agents = _agents_from_config(repo_root)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        try:
            agents = parse_agent_selection(args.agents)
        except ValueError as exc:
            parser.error(str(exc))
        if not agents:
            parser.error("--agents requires at least one agent name")

    if args.check:
        from chock.scaffold.recompile import compiled_differences

        drift = compiled_differences(repo_root, agents)
        if drift:
            print(f"Compiled artifacts are out of date ({len(drift)} difference(s)):")
            for line in drift:
                print(f"  {line}")
            print("Run `chock sync --repo .` and commit the result.")
            return 1
        print("Compiled artifacts match their manifests.")
        return 0

    try:
        coverage = recompile(repo_root, agents, skip_hooks=args.skip_hooks)
    except BookkeepingError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    print(f"Recompiled {len(coverage)} policies")
    for policy_id, cov in sorted(coverage.items()):
        print(f"{policy_id}:")
        for agent, level in sorted(cov.items()):
            print(f"  {agent}: {level}")
    return 0

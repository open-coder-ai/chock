"""Policy table, enable/disable toggles, and the full recompile command."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

import yaml

from chock.compile.levels import Grade, render_grade
from chock.compile.surfaces import AGENTS_ARG_REQUIRED_MSG
from chock.config import agents_from_config as _agents_from_config
from chock.config import load_config, policy_status, set_disabled
from chock.index.cli import cmd_refresh
from chock.manifest import ManifestSourceError, load_manifest
from chock.output import error, warn
from chock.policies import discover_policy_dirs
from chock.scaffold.adapters import parse_agent_selection
from chock.scaffold.recompile import BookkeepingError, compiled_differences, recompile


def _cell(value: Any) -> str:
    """One coverage cell as a table prints it; a pre-cell coverage.json still reads as its word."""
    return value if isinstance(value, str) else render_grade(Grade(**value))


def _parser_fail(parser: argparse.ArgumentParser, message: str) -> NoReturn:
    """`parser.error()` raises SystemExit; the raise below makes that provable statically."""
    parser.error(message)
    raise SystemExit(2)


def _load_manifest(pack_dir: Path) -> dict[str, Any]:
    warnings: list[str] = []
    try:
        result = load_manifest(pack_dir, warnings=warnings)
    except (yaml.YAMLError, OSError, ManifestSourceError) as exc:
        error(f"{pack_dir / 'manifest.yaml'}: manifest_parse: {exc}")
        return {}
    if result is None:
        return {}
    data, _ = result
    for warning in warnings:
        warn(f"{pack_dir}: manifest_default: {warning}")
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
    set_disabled(repo_root, args.policy_id, disabled=True)
    try:
        recompile(repo_root, agents)
    except BookkeepingError as exc:
        error(str(exc))
        return 1

    cmd_refresh(["--repo", str(repo_root)])
    print(f"Disabled {args.policy_id}")
    return 0


def enable_main(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(prog="chock enable")
    parser.add_argument("policy_id", help="Policy identifier to enable")
    parser.add_argument("--repo", default=".", help="Repo root")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    if _find_policy_manifest(repo_root, args.policy_id) is None:
        print(f"Unknown policy: {args.policy_id}", file=sys.stderr)
        return 2

    try:
        agents = _agents_from_config(repo_root)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    set_disabled(repo_root, args.policy_id, disabled=False)
    try:
        recompile(repo_root, agents)
    except BookkeepingError as exc:
        error(str(exc))
        return 1

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
    coverage: dict[str, dict[str, Any]] = {}
    if coverage_path.exists():
        try:
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            coverage = {}

    rows: list[tuple[str, str, str, str]] = []
    for policy_id in sorted(_policy_ids(repo_root)):
        manifest = _find_policy_manifest(repo_root, policy_id)
        status = policy_status(config, policy_id, manifest)
        cov = {agent: _cell(value) for agent, value in coverage.get(policy_id, {}).items()}
        if not cov:
            cov_str = "none"
        elif len(set(cov.values())) == 1:
            cov_str = next(iter(cov.values()))
        else:
            cov_str = "; ".join(f"{a}: {v}" for a, v in sorted(cov.items()))
        rows.append((policy_id, status["state"], cov_str, "yes" if status["mandatory"] else "no"))

    if not rows:
        print("No policies installed. This repo enforces nothing.")
        print("Copy a policy folder into .agents/policies/<id>/ and run `chock sync --repo .`.")
        return 0

    headers = ("id", "state", "coverage", "mandatory")
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)).rstrip())
    for row in rows:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip())
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
            _parser_fail(parser, str(exc))
    else:
        try:
            agents = parse_agent_selection(args.agents)
        except ValueError as exc:
            _parser_fail(parser, str(exc))
        if not agents:
            _parser_fail(parser, AGENTS_ARG_REQUIRED_MSG)

    if args.check:
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
        error(str(exc))
        return 1
    print(f"Recompiled {len(coverage)} policies")
    for policy_id, cov in sorted(coverage.items()):
        print(f"{policy_id}:")
        for agent, value in sorted(cov.items()):
            print(f"  {agent}: {_cell(value)}")
    return 0

"""Policy compiler: emit target-specific enforcement artifacts from a policy directory."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

import yaml

from chock.compile.emitters import (
    ambient,
    ci,
    claude_managed,
    git_hook,
    in_agent,
    mcp_gateway,
)
from chock.compile.levels import IN_AGENT_TODAY, Grade, render_grade
from chock.compile.surfaces import SURFACE_AGENTS, Surface, coverage_cell, parse_agent_selection
from chock.config import agents_from_config
from chock.hooks.in_agent_install import WIRED_VENDORS, installed_policy_ids
from chock.manifest import ManifestSourceError, load_manifest
from chock.policy_id import InvalidPolicyIdError, validate_policy_id
from chock.scaffold.install_ci import ci_workflow_installed
from chock.vendors import CHOCK_AGENT

DEFAULT_OUTPUT_ROOT = Path(".chock") / "compiled"

EMITTERS: dict[Surface, Any] = {
    Surface.GIT_HOOK: git_hook,
    Surface.CI_GATE: ci,
    Surface.PRE_TOOL_USE: in_agent.pre_tool_use,
    Surface.MANAGED_SETTING: claude_managed,
    Surface.AMBIENT_RULE: ambient,
    Surface.MCP_GATEWAY: mcp_gateway,
    Surface.AGENT_HOOKS: in_agent.agent_hooks,
}


@dataclass
class CompileResult:
    policy_id: str
    artifacts: dict[str, list[Path]] = field(default_factory=dict)
    coverage: dict[str, dict[str, dict[str, object]]] = field(default_factory=dict)


def _parser_fail(parser: argparse.ArgumentParser, message: str) -> NoReturn:
    """`parser.error()` raises SystemExit; the raise below makes that provable statically."""
    parser.error(message)
    raise SystemExit(2)


def _load_manifest(policy_dir: Path) -> dict[str, Any]:
    warnings: list[str] = []
    try:
        result = load_manifest(policy_dir, warnings=warnings)
    except (yaml.YAMLError, OSError, ManifestSourceError) as exc:
        print(f"[ERROR] {policy_dir / 'manifest.yaml'}: manifest_parse: {exc}", file=sys.stderr)
        return {}
    if result is None:
        return {}
    data, _ = result
    for warning in warnings:
        print(f"[WARN] {policy_dir}: manifest_default: {warning}", file=sys.stderr)
    return data


def _write_coverage(coverage_path: Path, entry: dict[str, dict[str, dict[str, object]]]) -> None:
    existing: dict[str, dict[str, dict[str, object]]] = {}
    if coverage_path.exists():
        try:
            existing = json.loads(coverage_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    existing.update(entry)
    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    coverage_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def compile_policy(
    policy_dir: Path,
    targets: list[str] | None = None,
    output_root: Path | None = None,
    agents: list[str] | None = None,
    repo_root: Path | None = None,
) -> CompileResult:
    """Compile a single policy directory into requested target artifacts."""
    policy_dir = Path(policy_dir).resolve()
    manifest = _load_manifest(policy_dir)
    policy_id = manifest.get("id") or policy_dir.name

    if not manifest:
        return CompileResult(policy_id=policy_id)

    try:
        validate_policy_id(policy_id, policy_dir.name)
    except InvalidPolicyIdError as exc:
        print(f"[ERROR] {policy_dir / 'manifest.yaml'}: manifest_id: {exc}", file=sys.stderr)
        return CompileResult(policy_id=policy_dir.name)

    output_root = Path(output_root) if output_root else DEFAULT_OUTPUT_ROOT
    output_base = output_root / policy_id

    requested = {Surface(t) for t in (targets or [s.value for s in Surface])}
    selected_targets = [s for s in Surface if s in requested]
    artifacts: dict[str, list[Path]] = {}

    for surface in selected_targets:
        emitter = EMITTERS.get(surface)
        if emitter is None:
            continue
        surface_dir = output_base / surface.value
        surface_dir.mkdir(parents=True, exist_ok=True)
        emitted = emitter.emit(policy_dir, surface_dir, manifest)
        artifacts[surface.value] = emitted
        if not emitted and surface_dir.exists():
            shutil.rmtree(surface_dir, ignore_errors=True)

    selected_set = {Surface(t) for t, paths in artifacts.items() if paths}
    agent_list = agents or sorted(SURFACE_AGENTS)
    root = Path(repo_root) if repo_root else output_root.parent.parent
    vendor_installed = {vendor: installed_policy_ids(root, vendor) for vendor in WIRED_VENDORS}
    installed_for = {
        agent: policy_id in vendor_installed[CHOCK_AGENT[agent]]
        for agent in IN_AGENT_TODAY
        if Surface.PRE_TOOL_USE in SURFACE_AGENTS[agent]
    }
    agent_hooks_for = {
        agent: policy_id in vendor_installed[CHOCK_AGENT[agent]]
        for agent in IN_AGENT_TODAY
        if Surface.AGENT_HOOKS in SURFACE_AGENTS[agent]
    }
    ci_installed = ci_workflow_installed(root)
    coverage: dict[str, dict[str, dict[str, object]]] = {policy_id: {}}
    for agent in agent_list:
        coverage[policy_id][agent] = coverage_cell(
            selected_set,
            agent,
            pre_tool_use_installed=installed_for.get(agent, False),
            ci_gate_installed=ci_installed,
            agent_hooks_installed=agent_hooks_for.get(agent, False),
        )._asdict()

    coverage_path = output_root.parent / "coverage.json"
    _write_coverage(coverage_path, coverage)

    return CompileResult(policy_id=policy_id, artifacts=artifacts, coverage=coverage)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile a Chock policy into target-surface artifacts")
    parser.add_argument("policy_id", help="Policy directory name under .agents/policies/")
    parser.add_argument(
        "--targets",
        nargs="*",
        default=[s.value for s in Surface],
        help="Surfaces to emit (default: all)",
    )
    parser.add_argument(
        "--agents",
        nargs="*",
        default=None,
        help="Agents to include in coverage report (comma- or space-separated; "
        "default: the repo's supported_agents, else all)",
    )
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument("--policy-dir", help="Path to policy directory (default: <repo>/.agents/policies/<policy_id>)")
    parser.add_argument("--output-root", help="Compiled output root (default: <repo>/.chock/compiled)")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    output_root = Path(args.output_root) if args.output_root else repo_root / DEFAULT_OUTPUT_ROOT

    if args.agents is None:
        try:
            agents = agents_from_config(repo_root)
        except ValueError as exc:
            _parser_fail(parser, str(exc))
    else:
        try:
            agents = parse_agent_selection(args.agents)
        except ValueError as exc:
            _parser_fail(parser, str(exc))
        if not agents:
            _parser_fail(parser, "--agents requires at least one agent name")

    policy_dir = Path(args.policy_dir) if args.policy_dir else repo_root / ".agents/policies" / args.policy_id
    if not policy_dir.exists():
        print(f"Policy directory not found: {policy_dir}", file=sys.stderr)
        return 2

    result = compile_policy(
        policy_dir,
        targets=args.targets,
        output_root=output_root,
        agents=agents,
        repo_root=repo_root,
    )

    print(f"Compiled {result.policy_id} to {output_root}")
    for surface, paths in sorted(result.artifacts.items()):
        if paths:
            print(f"  {surface}: {', '.join(str(p) for p in paths)}")
    print("Coverage:")
    for agent, cell in sorted(result.coverage.get(result.policy_id, {}).items()):
        print(f"  {agent}: {render_grade(Grade(**cell))}")
    return 0

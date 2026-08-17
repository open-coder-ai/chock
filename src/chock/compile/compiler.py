"""Policy compiler: emit target-specific enforcement artifacts from a policy directory."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

import yaml

from chock.compile.emitters import (
    ambient,
    ci,
    claude_managed,
    claude_pretooluse,
    git_hook,
)
from chock.compile.surfaces import SURFACE_AGENTS, Surface, coverage_level, parse_agent_selection
from chock.config import agents_from_config
from chock.hooks.cursor_install import installed_cursor_policy_ids
from chock.hooks.pretooluse_install import installed_pretooluse_policy_ids
from chock.manifest import ManifestSourceError, load_manifest
from chock.policy_id import InvalidPolicyId, validate_policy_id
from chock.scaffold.install_ci import ci_workflow_installed

DEFAULT_OUTPUT_ROOT = Path(".chock") / "compiled"

# `Surface.CI_GATE` was dropped from this map once, and the reason is worth keeping: the step
# it emitted could not fail. The push branch was `echo <hardcoded refs> | ... || true`, and the
# commit branch gated `git diff --cached` in a CI checkout, where there is no index. It is back
# because the runner now has a commit-range mode and `install-ci` writes a workflow that runs
# it -- emitting was never the bar, enforcing is. See docs/enforcement-surfaces.md.
EMITTERS: dict[Surface, Any] = {
    Surface.GIT_HOOK: git_hook,
    Surface.CI_GATE: ci,
    Surface.PRE_TOOL_USE: claude_pretooluse,
    Surface.MANAGED_SETTING: claude_managed,
    Surface.AMBIENT_RULE: ambient,
}


@dataclass
class CompileResult:
    policy_id: str
    artifacts: dict[str, list[Path]] = field(default_factory=dict)
    coverage: dict[str, dict[str, str]] = field(default_factory=dict)


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


def _write_coverage(coverage_path: Path, entry: dict[str, dict[str, str]]) -> None:
    existing: dict[str, dict[str, str]] = {}
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
    """Compile a single policy directory into requested target artifacts.

    Args:
        policy_dir: directory containing manifest.yaml and implementations/.
        targets: list of Surface values to emit; defaults to all surfaces.
        output_root: root directory for compiled artifacts; defaults to .chock/compiled.
        agents: agents to include in the coverage report; defaults to all known agents.

    Returns:
        CompileResult describing emitted artifacts and per-agent coverage.
    """
    policy_dir = Path(policy_dir).resolve()
    manifest = _load_manifest(policy_dir)
    policy_id = manifest.get("id") or policy_dir.name

    # A manifest that would not parse produces no artifacts. `_load_manifest` has already
    # reported it as `manifest_parse` and returned {}; continuing meant the emitters ran
    # anyway, and `git_hook` re-read the same file through `build_gate_json` -- which does
    # not catch YAML errors -- so `recompile` died with a raw ParserError traceback instead
    # of the diagnostic that had just been printed. Emitting a gate from a manifest nobody
    # could read would be worse still.
    if not manifest:
        return CompileResult(policy_id=policy_id)

    # The id becomes both the compiled-output directory and a token inside emitted git-hook
    # bash / CI run: blocks. Validate it here, at the choke point -- `validate` runs the same
    # rule, but a drop-in policy reaches the compiler without ever passing through validate.
    # On violation, emit nothing (like an unparseable manifest); the folder name, a real path
    # component, is the only safe thing left to name the result.
    try:
        validate_policy_id(policy_id, policy_dir.name)
    except InvalidPolicyId as exc:
        print(f"[ERROR] {policy_dir / 'manifest.yaml'}: manifest_id: {exc}", file=sys.stderr)
        return CompileResult(policy_id=policy_dir.name)

    output_root = Path(output_root) if output_root else DEFAULT_OUTPUT_ROOT
    output_base = output_root / policy_id

    requested = {Surface(t) for t in (targets or [s.value for s in Surface])}
    # Iterate in Surface declaration order, never in set order. Set iteration over enum
    # members follows hash order, which PYTHONHASHSEED randomises per process, so compiled
    # output was not reproducible: measured across seeds 0-7, protect-main-branch emitted
    # its ci-gate step in 5 runs and skipped it in 3. Determinism is also what makes a
    # byte-identity check on compiled gates meaningful evidence.
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

    # Only surfaces that actually produced a file count. The loop above records a key for
    # every attempted surface, including emitters that returned nothing, so keying off
    # `artifacts` alone credited a policy with surfaces it never emitted to.
    selected_set = {Surface(t) for t, paths in artifacts.items() if paths}
    agent_list = agents or sorted(SURFACE_AGENTS)
    # Derived, never mutated after the fact: see installed_pretooluse_policy_ids. The repo
    # root must be passed in, not inferred from output_root -- `recompile --check` compiles
    # into a temp directory, where inferring it would find no settings.json and silently
    # report every guard as unenforced.
    root = Path(repo_root) if repo_root else output_root.parent.parent
    # Per-agent witnesses: each agent's pre-tool-use claim needs ITS OWN install evidence.
    # A single flag would let wiring Claude raise `enforced` on Cursor rows too -- the
    # cross-agent variant of the overclaim `pre_tool_use_installed` exists to prevent.
    installed_for = {
        "claude": policy_id in installed_pretooluse_policy_ids(root),
        "cursor": policy_id in installed_cursor_policy_ids(root),
    }
    ci_installed = ci_workflow_installed(root)
    coverage: dict[str, dict[str, str]] = {policy_id: {}}
    for agent in agent_list:
        coverage[policy_id][agent] = coverage_level(
            selected_set,
            agent,
            pre_tool_use_installed=installed_for.get(agent, False),
            ci_gate_installed=ci_installed,
        )

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

    # The repo root is an explicit argument, like every other subcommand. It was inferred
    # from --output-root's grandparent once, which held only for the default layout: with
    # `--output-root out` the config lookup climbed out of the repo and fell back to all
    # thirteen agents -- the exact drift this resolution exists to prevent.
    repo_root = Path(args.repo).resolve()
    output_root = Path(args.output_root) if args.output_root else repo_root / DEFAULT_OUTPUT_ROOT

    # Same contract as init/sync/recompile: a selection mistake stops the run. The config
    # default matters as much as the parsing -- in a repo pinned to three agents, a bare
    # `compile` that defaulted to all of SURFACE_AGENTS rewrote coverage.json for thirteen
    # and put the repo into drift that `sync --check` then failed.
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
    for agent, level in sorted(result.coverage.get(result.policy_id, {}).items()):
        print(f"  {agent}: {level}")
    return 0

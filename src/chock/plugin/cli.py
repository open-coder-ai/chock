"""`chock plugin` -- package policies as Agent Plugins 1.0.0 directories."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chock.compile.compiler import _load_manifest
from chock.manifest import CANONICAL_MANIFEST
from chock.plugin.build import NAMESPACE, PluginNameError, build_plugin, plugin_differences
from chock.scaffold.recompile import discover_policy_dirs


def resolve_policy_dirs(repo_root: Path, policies_dir: str | None) -> list[Path]:
    """Policy directories to package.

    `--policies-dir` exists because a catalog is not an adopter. An adopter's policies live
    in `.agents/policies/` (what this repo enforces); a catalog's live in `base/` (what it
    publishes), and the catalog installs only a subset of what it ships. Defaulting to
    discovery and packaging only the installed six would have silently shipped half a
    catalog.
    """
    if policies_dir is None:
        return discover_policy_dirs(repo_root)
    root = repo_root / policies_dir
    if not root.is_dir():
        return []
    return sorted(p.parent for p in root.glob(f"*/{CANONICAL_MANIFEST}"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chock plugin",
        description="Package policies as Agent Plugins 1.0.0 directories (agent-plugins.org)",
    )
    parser.add_argument("action", choices=["build"], help="build: write plugin.json and skills/ per policy")
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument(
        "--policies-dir",
        default=None,
        help="Directory of policy folders relative to --repo (default: discover .agents/policies)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report policies whose packaged output is missing or stale, and exit non-zero. Writes nothing.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    policy_dirs = resolve_policy_dirs(repo_root, args.policies_dir)
    if not policy_dirs:
        print("No policies found to package.")
        return 0

    differences: list[str] = []
    written = 0
    for policy_dir in policy_dirs:
        manifest = _load_manifest(policy_dir)
        if not manifest:
            continue
        try:
            if args.check:
                differences.extend(plugin_differences(policy_dir, manifest, repo_root))
            else:
                build_plugin(policy_dir, manifest, repo_root)
                written += 1
        except PluginNameError as exc:
            print(f"[ERROR] {policy_dir}: {exc}", file=sys.stderr)
            return 2

    if args.check:
        if differences:
            print(f"Agent Plugins output is out of date ({len(differences)} difference(s)):")
            for line in differences:
                print(f"  {line}")
            print("Run `chock plugin build --repo .` and commit the result.")
            return 1
        print(f"Agent Plugins output matches manifests ({len(policy_dirs)} policies).")
        return 0

    print(f"Packaged {written} policies as Agent Plugins 1.0.0")
    print(f"  plugin.json + skills/<id>/SKILL.md per policy; enforcement metadata under {NAMESPACE}")
    print("  Skills are advisory in any client. Enforcement still needs `chock sync`.")
    return 0

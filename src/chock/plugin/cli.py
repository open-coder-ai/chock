"""`chock plugin` -- package policies as installable plugin directories.

Two formats from one source. `agent-plugins` (the default) emits the Agent Plugins 1.0.0
manifest and skill in place, the spec authors' own add-portability-first migration.
`claude` emits Claude Code's plugin layout -- read natively by Claude Code, Copilot CLI,
VS Code, and Grok Build -- and always into a distribution tree (`--out-dir`), never in
place: a `.claude-plugin/` directory inside a policy folder would be discovered by any
client pointed at the repo and read as a plugin nobody published.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from chock.compile.compiler import _load_manifest
from chock.manifest import CANONICAL_MANIFEST
from chock.plugin.build import (
    NAMESPACE,
    PluginNameError,
    build_plugin,
    plugin_differences,
    plugin_name,
)
from chock.plugin.claude import build_claude_plugin, claude_plugin_differences
from chock.scaffold.recompile import discover_policy_dirs

FORMATS = ("agent-plugins", "claude")


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
        description="Package policies as installable plugin directories",
    )
    parser.add_argument("action", choices=["build"], help="build: render each policy's plugin files")
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument(
        "--policies-dir",
        default=None,
        help="Directory of policy folders relative to --repo (default: discover .agents/policies)",
    )
    parser.add_argument(
        "--format",
        choices=[*FORMATS, "all"],
        default="agent-plugins",
        help="Plugin format to emit (default: agent-plugins)",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Distribution root: plugins are written to <out-dir>/<format>/<id>/ (required for claude format)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report policies whose packaged output is missing or stale, and exit non-zero. Writes nothing.",
    )
    args = parser.parse_args(argv)

    formats = list(FORMATS) if args.format == "all" else [args.format]
    if "claude" in formats and args.out_dir is None:
        print(
            "--format claude requires --out-dir; see `chock plugin --help` for why in-place is refused.",
            file=sys.stderr,
        )
        return 2

    repo_root = Path(args.repo).resolve()
    out_root = Path(args.out_dir).resolve() if args.out_dir else None
    policy_dirs = resolve_policy_dirs(repo_root, args.policies_dir)
    if not policy_dirs:
        print("No policies found to package.")
        return 0

    differences: list[str] = []
    written = 0
    # Two policy folders can declare the same manifest id -- the id is not required to match
    # the folder name in every catalog layout. They would map to one distribution directory,
    # the second silently overwriting the first while the run reported both as packaged, and
    # the index would list one package built from a mixture of two policies' files.
    seen: dict[str, Path] = {}
    for policy_dir in policy_dirs:
        manifest = _load_manifest(policy_dir)
        if not manifest:
            continue
        try:
            policy_id = str(manifest.get("id") or policy_dir.name)
            name = plugin_name(policy_id)
            if name in seen:
                print(
                    f"[ERROR] duplicate policy id {policy_id!r}: {seen[name]} and {policy_dir} "
                    f"would package into the same directory. Give them distinct ids.",
                    file=sys.stderr,
                )
                return 2
            seen[name] = policy_dir
            for fmt in formats:
                # One subtree per format, never a shared directory. The formats disagree by
                # design: a Claude package that ships hooks says the policy is enforced here,
                # while the same policy in the hookless Agent Plugins format is advisory. Both
                # statements are true of their own package and false of the other, so sharing
                # `skills/<id>/SKILL.md` would force one of them to lie -- and a generic client
                # reading a shared tree would see an enforcement claim for hooks it ignores.
                target = out_root / fmt / name if out_root else None
                if fmt == "agent-plugins":
                    if args.check:
                        differences.extend(plugin_differences(policy_dir, manifest, repo_root, target))
                    else:
                        build_plugin(policy_dir, manifest, repo_root, out_dir=target)
                else:
                    assert target is not None  # enforced above: claude format requires --out-dir
                    if args.check:
                        differences.extend(claude_plugin_differences(policy_dir, manifest, repo_root, target))
                    else:
                        build_claude_plugin(policy_dir, manifest, repo_root, target)
            if not args.check:
                written += 1
        except PluginNameError as exc:
            print(f"[ERROR] {policy_dir}: {exc}", file=sys.stderr)
            return 2

    # A policy removed or renamed upstream leaves its directory behind. Nothing would rebuild
    # it, nothing would report it, and `marketplace build` would keep indexing it -- so a
    # withdrawn policy stays installable forever, which is the yank procedure failing
    # silently. Only formats that were actually built are reconciled.
    if out_root is not None:
        for fmt in formats:
            tree = out_root / fmt
            if not tree.is_dir():
                continue
            for stale_dir in sorted(d for d in tree.iterdir() if d.is_dir() and d.name not in seen):
                if args.check:
                    differences.append(f"stale: {fmt}/{stale_dir.name} (no policy produces it)")
                else:
                    shutil.rmtree(stale_dir)
                    print(f"  removed {fmt}/{stale_dir.name}: no policy produces it any more")

    if args.check:
        if differences:
            print(f"Plugin output is out of date ({len(differences)} difference(s)):")
            for line in differences:
                print(f"  {line}")
            print("Run `chock plugin build` with the same arguments and commit the result.")
            return 1
        print(f"Plugin output matches manifests ({len(policy_dirs)} policies, format: {args.format}).")
        return 0

    print(f"Packaged {written} policies (format: {args.format})")
    if "agent-plugins" in formats:
        print(f"  plugin.json + skills/<id>/SKILL.md per policy; enforcement metadata under {NAMESPACE}")
    if "claude" in formats:
        print(
            "  .claude-plugin/plugin.json + hooks/ + scripts/ per guard policy; fail posture stated in each description"
        )
    print("  Skills are advisory in any client. Repo-level enforcement still needs `chock sync`.")
    return 0

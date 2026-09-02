"""`chock plugin` -- package policies as installable plugin directories."""

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
from chock.plugin.codex import build_codex_plugin, codex_plugin_differences
from chock.plugin.copilot import build_copilot_plugin, copilot_plugin_differences
from chock.plugin.cursor import build_cursor_plugin, cursor_plugin_differences
from chock.scaffold.recompile import discover_policy_dirs

FORMATS = ("agent-plugins", "claude", "copilot", "cursor", "codex")

HOOK_FORMATS = frozenset({"claude", "copilot", "cursor", "codex"})

HOOK_EMITTERS = {
    "claude": (claude_plugin_differences, build_claude_plugin),
    "copilot": (copilot_plugin_differences, build_copilot_plugin),
    "cursor": (cursor_plugin_differences, build_cursor_plugin),
    "codex": (codex_plugin_differences, build_codex_plugin),
}


def resolve_policy_dirs(repo_root: Path, policies_dir: str | None) -> list[Path]:
    """Policy directories to package."""
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
        help="Distribution root: plugins are written to <out-dir>/<format>/<id>/ (required for every hook-carrying format)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report policies whose packaged output is missing or stale, and exit non-zero. Writes nothing.",
    )
    args = parser.parse_args(argv)

    formats = list(FORMATS) if args.format == "all" else [args.format]
    hook_formats = sorted(HOOK_FORMATS.intersection(formats))
    if hook_formats and args.out_dir is None:
        print(
            f"--format {hook_formats[0]} requires --out-dir; see `chock plugin --help` for why in-place is refused.",
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
                target = out_root / fmt / name if out_root else None
                if fmt == "agent-plugins":
                    if args.check:
                        differences.extend(plugin_differences(policy_dir, manifest, repo_root, target))
                    else:
                        build_plugin(policy_dir, manifest, repo_root, out_dir=target)
                else:
                    assert target is not None  # noqa: S101 -- hook_formats requiring --out-dir was checked above
                    differ, build = HOOK_EMITTERS[fmt]
                    if args.check:
                        differences.extend(differ(policy_dir, manifest, repo_root, target))
                    else:
                        build(policy_dir, manifest, repo_root, target)
            if not args.check:
                written += 1
        except PluginNameError as exc:
            print(f"[ERROR] {policy_dir}: {exc}", file=sys.stderr)
            return 2

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
    if "copilot" in formats:
        print("  root plugin.json + com.github.copilot/hooks/ per guard policy; same posture discipline")
    if "cursor" in formats:
        print("  .cursor-plugin/plugin.json + hooks/ (beforeShellExecution) per guard policy")
    if "codex" in formats:
        print("  .codex-plugin/plugin.json + hooks/ (PreToolUse) per guard policy")
    print("  Skills are advisory in any client. Repo-level enforcement still needs `chock sync`.")
    return 0

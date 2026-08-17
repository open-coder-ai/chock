"""Chock module (auto-organized from the original monolith)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from chock.registry.core import (
    RegistryEntry,
    ensure_registry_dir,
    load_registry,
    registry_path,
    repo_root,
    resolve,
    save_registry,
    scan,
)
from chock.validation.report import Finding, Report


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else repo_root()
    ensure_registry_dir(root)
    if not registry_path(root).exists():
        save_registry({}, root)
    print(f"Initialized empty registry at {registry_path(root)}")
    return 0


def _render_skips(skips: list, report: Report) -> None:
    for skip in skips:
        report.add(Finding(str(skip.path), "manifest_parse", "error", skip.reason))


def _print_summary(entries: dict, skips: list) -> None:
    total = sum(len(v) for v in entries.values())
    summary = f"Scanned {total} artifact(s) across {len(entries)} unique ID(s)"
    if skips:
        summary += f", {len(skips)} skipped (unreadable)"
    summary += "."
    print(summary)


def cmd_scan(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else repo_root()
    entries, skips = scan(root)
    save_registry(entries, root)

    report = Report()
    _render_skips(skips, report)
    for finding in report.errors:
        print(f"[ERROR] {finding.path} :: {finding.check}: {finding.message}")

    _print_summary(entries, skips)
    print(f"Registry written to {registry_path(root)}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else repo_root()
    entries = load_registry(root)
    filtered: list[RegistryEntry] = []
    for versions in entries.values():
        for e in versions:
            if args.type and e.artifact != args.type:
                continue
            filtered.append(e)
    for e in sorted(filtered, key=lambda x: (x.artifact, x.id, x.version)):
        print(f"{e.artifact:14} {e.id:30} {e.version:12} {e.path}")
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else repo_root()
    entry = resolve(args.id, args.version, args.type, root)
    if not entry:
        print(
            f"ERROR: no registry entry for {args.id}"
            + (f" version {args.version}" if args.version else "")
            + (f" type {args.type}" if args.type else ""),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(asdict(entry), indent=2))
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else repo_root()
    entry = resolve(args.id, args.version, args.type, root)
    if not entry:
        print(
            f"ERROR: no registry entry for {args.id}"
            + (f" version {args.version}" if args.version else "")
            + (f" type {args.type}" if args.type else ""),
            file=sys.stderr,
        )
        return 1
    manifest_path = root / entry.path / entry.manifest
    print(manifest_path.resolve())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chock local JSON registry")
    parser.add_argument("--root", "--repo", dest="root", help="Repo root (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create an empty registry")
    p_scan = sub.add_parser("scan", help="Scan repo and rebuild registry")
    p_scan.add_argument("--root", "--repo", dest="root", help="Repo root")

    p_list = sub.add_parser("list", help="List registered artifacts")
    p_list.add_argument("--type", help="Filter by artifact type")
    p_list.add_argument("--root", "--repo", dest="root", help="Repo root")

    p_get = sub.add_parser("get", help="Get registry metadata for an ID")
    p_get.add_argument("id")
    p_get.add_argument("--version", help="Exact version")
    p_get.add_argument("--type", help="Artifact type filter (skill|hook|rule|...)")
    p_get.add_argument("--root", "--repo", dest="root", help="Repo root")

    p_resolve = sub.add_parser("resolve", help="Resolve ID to manifest path")
    p_resolve.add_argument("id")
    p_resolve.add_argument("--version", help="Exact version")
    p_resolve.add_argument("--type", help="Artifact type filter (skill|hook|rule|...)")
    p_resolve.add_argument("--root", "--repo", dest="root", help="Repo root")

    args = parser.parse_args(argv)
    commands = {
        "init": cmd_init,
        "scan": cmd_scan,
        "list": cmd_list,
        "get": cmd_get,
        "resolve": cmd_resolve,
    }
    return commands[args.command](args)

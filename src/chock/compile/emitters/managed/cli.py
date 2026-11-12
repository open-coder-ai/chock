"""`chock emit --managed <vendor> --out <dir>`: write a managed-settings bundle for an admin to deploy; deploy nothing."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from chock.compile.emitters import managed
from chock.compile.emitters.managed import claude_code
from chock.config import load_config, policy_status
from chock.manifest import load_manifest, warn_defaults
from chock.output import error, legible
from chock.policies import discover_policy_dirs
from chock.policy_id import InvalidPolicyIdError, validate_policy_id

BUILDERS = {claude_code.VENDOR: claude_code}
DEPLOY_FILE = "deploy.json"
LABELS_FILE = "labels.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chock emit",
        description=(
            "Write one vendor's managed-settings file, the self-contained hook bundle it runs, deploy.json "
            "(where an admin places each part, what it needs, how to undo it) and labels.json, all under --out. "
            "It writes no system path, elevates nothing and deploys nothing. Every label is vendor-docs "
            "evidence, unwitnessed, at most best-effort; a local administrator can still edit or remove the file."
        ),
    )
    parser.add_argument("--managed", required=True, choices=managed.VENDORS, help="the vendor to emit for")
    parser.add_argument(
        "--out", required=True, type=Path, help="a folder outside any system path; <out>/<vendor>/ must not exist"
    )
    parser.add_argument(
        "--repo", type=Path, default=Path(), help="the repository whose policies are emitted (default: .)"
    )
    parser.add_argument(
        "--policies", help="comma-separated policy ids (default: every enabled policy with a guard or gate)"
    )
    parser.add_argument("--platform", choices=managed.PLATFORMS, help="the OS the file is for (default: this one)")
    parser.add_argument(
        "--deploy-root",
        help="absolute folder the admin copies bundle/ to (default: the vendor's admin folder + /chock)",
    )
    parser.add_argument(
        "--lock",
        action="store_true",
        help="also emit the vendor's managed-hooks-only key, which stops every user, project and plugin hook on the machine",
    )
    return parser


def _manifest(policy_dir: Path) -> dict[str, Any]:
    warnings: list[str] = []
    result = load_manifest(policy_dir, warnings=warnings)
    if result is None:
        return {}
    data, path = result
    warn_defaults(path, warnings)
    return data


def _selected(repo: Path, wanted: str | None) -> list[tuple[str, Path, dict[str, Any]]]:
    """(id, folder, manifest) of each policy to emit: the named ones, else every one the config leaves enabled."""
    found = {path.name: path for path in discover_policy_dirs(repo)}
    names = [name.strip() for name in wanted.split(",") if name.strip()] if wanted else sorted(found)
    missing = [name for name in names if name not in found]
    if missing:
        msg = f"no policy {', '.join(missing)} under {repo / '.agents' / 'policies'}"
        raise managed.EmitRefusedError(msg)
    config = load_config(repo)
    chosen = []
    for name in names:
        manifest = _manifest(found[name])
        policy_id = str(manifest.get("id") or name)
        try:
            validate_policy_id(policy_id, name)
        except InvalidPolicyIdError as exc:
            raise managed.EmitRefusedError(str(exc)) from exc
        if wanted or policy_status(config, policy_id, manifest)["state"] != "disabled":
            chosen.append((policy_id, found[name], manifest))
    return chosen


def _report(dest: Path, plan: dict[str, Any], labels: list[dict[str, Any]], skipped: list[str]) -> str:
    lines = [f"chock emit: wrote {dest} for {plan['vendor']} on {plan['platform']}; nothing was deployed."]
    lines += [f"  place {step['from']} at {step['to']}" for step in plan["place"]]
    lines += [
        f"  {row['policy']}: {row['label']}, {'witnessed' if row['witnessed'] else 'unwitnessed'}" for row in labels
    ]
    lines += [f"  skipped {policy_id}: no shell guard or write gate to run" for policy_id in skipped]
    lines += [f"  {note}" for note in plan["notes"]]
    lines.append(f"  {DEPLOY_FILE} lists what each machine needs, what this does not promise, and the undo step.")
    return "\n".join(lines) + "\n"


def emit(args: argparse.Namespace) -> str:
    """Build in memory, check every refusal, then write the tree; returns the report."""
    builder = BUILDERS[args.managed]
    facts = managed.facts(args.managed)
    platform = args.platform or managed.host_platform()
    root = managed.deploy_root(args.deploy_root or facts["deploy_root"][platform], platform)
    dest = managed.vendor_out(args.out, args.managed)
    repo = args.repo.resolve()
    files, labels, skipped = builder.build(_selected(repo, args.policies), repo, root, lock=args.lock)
    if not labels:
        msg = "no selected policy has a shell guard or a write gate, so there is nothing for a managed hook to run"
        raise managed.EmitRefusedError(msg)
    plan = builder.deploy_plan(platform, root, lock=args.lock)
    plan["deploy_root"] = root
    files[PurePosixPath(DEPLOY_FILE)] = managed.as_json(plan)
    files[PurePosixPath(LABELS_FILE)] = managed.as_json(labels)
    managed.write_tree(dest, files)
    return _report(dest, plan, labels, skipped)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = emit(args)
    except managed.EmitRefusedError as exc:
        error(f"chock emit: {exc}")
        return 1
    sys.stdout.write(legible(report))
    return 0

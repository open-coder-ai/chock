"""Generate a compliance coverage report across policies."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from chock.config import _disabled_list, load_config
from chock.manifest import ManifestSourceError, load_manifest
from chock.scaffold.recompile import discover_policy_dirs

DATA_DIR = Path(__file__).parent / "data"


BUILTIN_FRAMEWORKS = {p.stem for p in sorted(DATA_DIR.glob("*.json"))}


def _load_builtin_controls(framework: str) -> dict[str, str]:
    if framework not in BUILTIN_FRAMEWORKS:
        return {}
    data = json.loads((DATA_DIR / f"{framework}.json").read_text(encoding="utf-8"))
    return {c["id"]: c["title"] for c in data.get("controls", [])}


def _parse_claim(claim: Any) -> tuple[str, str, str] | None:
    """Return (control, coverage, note) for a ClaimEntry."""
    if isinstance(claim, str):
        return claim, "partial", ""
    if not isinstance(claim, dict):
        return None
    control = claim.get("control")
    if not control:
        return None
    coverage = claim.get("coverage", "partial")
    if coverage not in ("full", "partial"):
        coverage = "partial"
    note = claim.get("note", "")
    return control, coverage, note


def _collect_claims(repo_root: Path, framework: str) -> dict[str, list[tuple[str, str, str]]]:
    """Map control id -> list of (policy_id, coverage, note)."""
    disabled = _disabled_list(load_config(repo_root))
    compiled_root = repo_root / ".chock" / "compiled"
    repo_compiled = (repo_root / ".chock" / "coverage.json").exists()
    claims: dict[str, list[tuple[str, str, str]]] = {}
    for pack_dir in discover_policy_dirs(repo_root):
        try:
            result = load_manifest(pack_dir)
            if result is None:
                continue
            manifest, _ = result
        except (yaml.YAMLError, OSError, ManifestSourceError):
            continue

        compliance = manifest.get("compliance") or {}
        framework_claims = compliance.get(framework)
        if not isinstance(framework_claims, list):
            continue

        policy_id = manifest.get("id") or pack_dir.name
        if policy_id in disabled:
            continue
        if repo_compiled:
            out = compiled_root / policy_id
            if not (out.is_dir() and any(out.iterdir())):
                continue
        for claim in framework_claims:
            parsed = _parse_claim(claim)
            if parsed is None:
                continue
            control, coverage, note = parsed
            claims.setdefault(control, []).append((policy_id, coverage, note))
    return claims


def _control_state(policies: list[tuple[str, str, str]]) -> str:
    if any(coverage == "full" for _, coverage, _ in policies):
        return "covered"
    if policies:
        return "partial"
    return "uncovered"


def _build_report(
    repo_root: Path,
    framework: str,
) -> dict[str, Any]:
    builtin = _load_builtin_controls(framework)
    claims = _collect_claims(repo_root, framework)

    control_ids = list(builtin.keys()) if framework in BUILTIN_FRAMEWORKS else sorted(claims.keys())

    report: dict[str, Any] = {framework: {}}
    for control_id in control_ids:
        policies = sorted(claims.get(control_id, []))
        state = _control_state(policies)
        report[framework][control_id] = {
            "state": state,
            "policies": [
                {"id": policy_id, "coverage": coverage, "note": note} for policy_id, coverage, note in policies
            ],
        }
    return report


def _format_table(
    report: dict[str, Any],
    framework: str,
) -> list[str]:
    builtin = _load_builtin_controls(framework)
    lines: list[str] = []
    lines.append(f"Framework: {framework}")
    lines.append(f"{'Control':<12} {'State':<10} {'Title / Covering policies'}")
    lines.append("-" * 70)
    for control_id in report[framework]:
        entry = report[framework][control_id]
        state = entry["state"]
        title = builtin.get(control_id, "")
        policies = entry["policies"]
        if policies:
            policy_strs = [f"{p['id']} ({p['coverage']})" for p in policies]
            detail = ", ".join(policy_strs)
        else:
            detail = "-"
        first = f"{control_id:<12} {state:<10} {title}" if title else f"{control_id:<12} {state:<10} {detail}"
        lines.append(first)
        if title and policies:
            lines.append(f"{'':<12} {'':<10} {detail}")
    return lines


def _parse_report_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="chock compliance report")
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument(
        "--framework",
        default="owasp_asi",
        help="Compliance framework to report on",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = []
    if not argv or argv[0] in ("-h", "--help", "help"):
        print("Usage: chock compliance report [--repo .] [--framework owasp_asi] [--json]")
        return 0
    if argv[0] != "report":
        print(f"Unknown compliance subcommand: {argv[0]!r}. Usage: chock compliance report ...", file=sys.stderr)
        return 2

    args = _parse_report_args(argv[1:])
    repo_root = Path(args.repo).resolve()
    if not repo_root.exists():
        print(f"Repo not found: {repo_root}", file=sys.stderr)
        return 2
    if args.framework not in BUILTIN_FRAMEWORKS and not _collect_claims(repo_root, args.framework):
        print(
            f"Unknown framework {args.framework!r} and no policy declares claims for it. "
            f"Known: {', '.join(sorted(BUILTIN_FRAMEWORKS))}.",
            file=sys.stderr,
        )
        return 2

    report = _build_report(repo_root, args.framework)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for line in _format_table(report, args.framework):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

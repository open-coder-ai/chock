"""`chock install --selection <file | URL | code> [--dest DIR] [--apply]`."""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from chock.install import package, resolve, selection, warnings
from chock.scaffold.pin import PinError, fetch_catalog

DEFAULT_DEST = Path("~/.chock/marketplace")


def _commands(dest: Path) -> list[list[str]]:
    data = package.settings()
    tokens = {"__DEST__": str(dest), "__PLUGIN__": data["plugin"], "__MARKETPLACE__": data["marketplace"]}
    out = []
    for template in data["commands"]:
        line = []
        for part in template:
            for token, value in tokens.items():
                part = part.replace(token, value)  # noqa: PLW2901 -- each token substituted in turn
            line.append(part)
        out.append(line)
    return out


def _report(labels: list[package.Label], lines: list[str]) -> None:
    words = package.settings()["labels"]
    width = max(len(label.policy_id) for label in labels)
    print("Each policy, on Claude Code:")
    for label in labels:
        print(f"  {label.policy_id:{width}}  {words[label.keyword]:8}  {label.says}")
        print(f"  {'':{width}}  {'':8}  {label.description}")
    for line in lines:
        print(f"warning: {line}")
    print(package.settings()["disclaimer"])


def _apply(commands: list[list[str]]) -> int:
    """Run the client's own commands; chock never edits Claude Code's settings files."""
    if shutil.which("claude") is None:
        print(
            "chock install: --apply needs the `claude` command on PATH; run the commands above instead.",
            file=sys.stderr,
        )
        return 1
    for command in commands:
        print(f"$ {shlex.join(command)}", flush=True)
        result = subprocess.run(command, check=False)  # noqa: S603 -- the fixed client commands this flag exists to run
        if result.returncode != 0:
            print(f"chock install: `{shlex.join(command)}` exited {result.returncode}", file=sys.stderr)
            return result.returncode
    return 0


def install(chosen: dict[str, Any], dest: Path) -> tuple[list[package.Label], list[str]]:
    """Fetch, verify, label and build; returns (labels, warnings)."""
    catalog_spec = chosen["catalog"]
    with tempfile.TemporaryDirectory(prefix="chock-install-") as tmp:
        catalog, _commit = fetch_catalog(catalog_spec["source"], catalog_spec["ref"], Path(tmp) / "catalog")
        members = resolve.members(catalog, chosen)
        labels = package.labels(members, catalog)
        keywords = {label.policy_id: label.keyword for label in labels}
        lines = warnings.warnings_for([m.id for m in members], keywords, Path.cwd(), warnings.load_rules())
        version = f"{package.settings()['version']}+{selection.digest(chosen)[:12]}"
        package.replace(dest, lambda into: package.stage(members, catalog, chosen, into, version))
    return labels, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chock install", description="Build a chock selection into one Claude Code plugin in a local marketplace"
    )
    parser.add_argument("--selection", required=True, help="chock.selection.yaml, a URL with #s=..., or the bare code")
    parser.add_argument("--dest", default=str(DEFAULT_DEST), help=f"Marketplace directory (default {DEFAULT_DEST})")
    parser.add_argument("--apply", action="store_true", help="Also run the two `claude plugin` commands")
    args = parser.parse_args(argv)

    dest = Path(args.dest).expanduser().resolve()
    try:
        chosen = selection.load(args.selection)
        labels, lines = install(chosen, dest)
    except PinError as exc:
        print(exc, file=sys.stderr)
        return 2
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"chock install: {exc}", file=sys.stderr)
        return 1

    print(f"Built {package.settings()['plugin']} ({len(labels)} policies) in {dest}")
    print(f"  from {chosen['catalog']['source']} at {chosen['catalog']['ref']}")
    _report(labels, lines)
    commands = _commands(dest)
    print("Next:" if not args.apply else "Running:")
    for command in commands:
        print(f"  {shlex.join(command)}")
    print(package.settings()["reload"])
    return _apply(commands) if args.apply else 0


if __name__ == "__main__":
    raise SystemExit(main())

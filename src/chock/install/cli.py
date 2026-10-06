"""`chock install --selection <file | URL | code> [--client C] [--dest DIR] [--apply]`."""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from chock.install import package, place, resolve, selection, steps, trust, warnings
from chock.scaffold.add import IntegrityError
from chock.scaffold.pin import PinError, fetch_catalog

#: The five client ids, in the order data/install.json lists them.
CLIENTS = tuple(package.settings()["clients"])


def _report(client_id: str, labels: list[package.Label], lines: list[str]) -> None:
    words = package.settings()["labels"]
    width = max(len(label.policy_id) for label in labels)
    print(f"Each policy, on {package.client(client_id)['name']}:")
    for label in labels:
        print(f"  {label.policy_id:{width}}  {words[label.keyword]:8}  {label.says}")
        print(f"  {'':{width}}  {'':8}  {label.description}")
    for line in lines:
        print(f"warning: {line}")
    print(package.settings()["disclaimer"])


def _show(rendered: list[steps.Step], *, applying: bool) -> None:
    """Print every step; the header says whether `--apply` runs the commands now."""
    print("Running:" if applying and any(s.command for s in rendered) else "Next:")
    for step in rendered:
        if step.command:
            print(f"  {shlex.join(step.command)}")
        else:
            print("\n".join(f"  {line}" for line in step.text.splitlines()))


def _apply(client_id: str, rendered: list[steps.Step]) -> int:
    """Run the client's own commands, only when its binary is on PATH; notes and settings stay the user's."""
    commands = [s.command for s in rendered if s.command]
    data = package.client(client_id)
    if not commands:
        print(f"chock install: {data['name']} has no command to run; follow the steps above.")
        return 0
    if shutil.which(data["binary"]) is None:
        print(
            f"chock install: --apply needs the `{data['binary']}` command on PATH; run the commands above instead.",
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


def _refuse_local(chosen: dict[str, Any]) -> None:
    """Local policy folders are part of schema 2 but are not built by this engine yet."""
    local = [p["id"] for p in chosen["policies"] if p["from"] == selection.LOCAL]
    if local:
        msg = (
            f"{', '.join(local)}: local policies (from: local) are not yet supported by this version of chock; "
            f"remove them from the selection or install them with a later chock. {resolve.REFUSED}"
        )
        raise IntegrityError(msg)


def install(chosen: dict[str, Any], dest: Path, allowed: list[str]) -> tuple[list[package.Label], list[str]]:
    """Trust, fetch, verify, label and build the selection for its client; returns (labels, warnings)."""
    _refuse_local(chosen)
    client_id, name = chosen["client"], chosen["bundle"]["name"]
    place.check_owned(client_id, dest, name)
    source, ref = chosen["catalog"]["source"], chosen["catalog"]["ref"]
    trust.check_source(source, allowed)
    with tempfile.TemporaryDirectory(prefix="chock-install-") as tmp:
        catalog, _commit = fetch_catalog(source, ref, Path(tmp) / "catalog")
        trust.require_on_branch(source, ref, Path(tmp) / "published")
        members = resolve.members(catalog, chosen)
        labels = package.labels(members, catalog, client_id)
        grades = {label.policy_id: label.keyword for label in labels}
        context = warnings.Context(
            [m.id for m in members], grades, Path.cwd(), client_id, place.others(client_id, dest, name)
        )
        lines = warnings.warnings_for(context, warnings.load_rules())
        version = f"{chosen['bundle']['version']}+{selection.digest(chosen)[:12]}"
        if package.client(client_id)["layout"] == place.MARKETPLACE:
            place.migrate_legacy(dest)
        target = place.plugin_dir(client_id, dest, name)
        package.replace(target, lambda into: package.stage(members, catalog, chosen, into, version))
        place.write_marketplace(client_id, dest)
    return labels, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chock install", description="Build a chock selection into one plugin for one agent"
    )
    parser.add_argument("--selection", required=True, help="chock.selection.yaml, a URL with #s=..., or the bare code")
    parser.add_argument("--client", choices=CLIENTS, help="The agent to build for (default: the selection's client)")
    parser.add_argument("--dest", help="Install folder (default: the client's own, e.g. ~/.chock/marketplace/<client>)")
    parser.add_argument("--apply", action="store_true", help="Also run the client's own install commands, if any")
    parser.add_argument(
        "--allow-source",
        action="append",
        default=[],
        metavar="SOURCE",
        help="Also trust this exact catalog source (the selection itself can never widen trust)",
    )
    args = parser.parse_args(argv)

    try:
        chosen = selection.load(args.selection)
        chosen = {**chosen, "client": args.client or chosen["client"]}
        client_id, name = chosen["client"], chosen["bundle"]["name"]
        dest = (Path(args.dest).expanduser() if args.dest else place.default_dest(client_id)).resolve()
        if "catalog" in chosen:
            print(f"Catalog source: {chosen['catalog']['source']}")
            print(f"Catalog ref:    {chosen['catalog']['ref']}", flush=True)
        labels, lines = install(chosen, dest, args.allow_source)
    except PinError as exc:
        print(exc, file=sys.stderr)
        return 2
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"chock install: {exc}", file=sys.stderr)
        return 1

    folder = place.plugin_dir(client_id, dest, name)
    print(f"Built {name} ({len(labels)} policies) for {package.client(client_id)['name']} in {folder}")
    _report(client_id, labels, lines)
    tokens = {
        "__DEST__": str(dest),
        "__PLUGIN_DIR__": str(folder),
        "__PLUGIN__": name,
        "__MARKETPLACE__": package.settings()["marketplace"],
    }
    rendered = steps.render(client_id, tokens)
    _show(rendered, applying=args.apply)
    return _apply(client_id, rendered) if args.apply else 0


if __name__ == "__main__":
    raise SystemExit(main())

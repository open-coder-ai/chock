"""`chock install --selection <file | URL | code> [--client C] [--dest DIR] [--apply]`."""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chock.compile.compiler import _load_manifest
from chock.install import claude_plugin, local, package, place, resolve, selection, steps, trust, warnings
from chock.plugin.bundle_build import Member
from chock.scaffold.add import IntegrityError
from chock.scaffold.pin import PinError, fetch_catalog

#: The client ids, in the order data/install.json lists them.
CLIENTS = tuple(package.settings()["clients"])
#: No longer built for: Antigravity CLI replaced Gemini CLI for unpaid users. Accepted only to say so.
RETIRED = "gemini-cli"


def _report(client_id: str, labels: list[package.Label], lines: list[str]) -> None:
    words = package.settings()["labels"]
    width = max(len(label.policy_id) for label in labels)
    print(f"Each policy, on {package.client(client_id)['name']}:")
    custom = package.settings()["origin"]["custom"]
    for label in labels:
        says = f"{custom}; {label.says}" if label.custom else label.says
        print(f"  {label.policy_id:{width}}  {words[label.keyword]:8}  {local.visible(says)}")
        print(f"  {'':{width}}  {'':8}  {local.visible(label.description)}")
    for line in lines:
        print(f"warning: {line}")
    print(package.settings()["disclaimer"])


def _show(rendered: list[steps.Step], *, applying: bool) -> None:
    """Print every step; the header says whether `--apply` runs the commands now."""
    _print_steps("Running:" if applying and any(s.command for s in rendered) else "Next:", rendered)


def _print_steps(header: str, rendered: list[steps.Step]) -> None:
    print(header)
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


@dataclass(frozen=True)
class Options:
    """What the command line adds to a selection: trusted sources, folder, local-code trust and marketplace name."""

    allowed: list[str]
    base: Path | None = None
    trust_local: dict[str, str] = field(default_factory=dict)
    interactive: bool = False
    marketplace: str = field(default_factory=package.marketplace)


def _catalog(chosen: dict[str, Any], allowed: list[str], work: Path) -> Path:
    """The selection's catalog at its pinned commit, from a trusted source and on its published branch."""
    source, ref = chosen["catalog"]["source"], chosen["catalog"]["ref"]
    trust.check_source(source, allowed)
    catalog, _commit = fetch_catalog(source, ref, work / "catalog")
    trust.require_on_branch(source, ref, work / "published")
    return catalog


def _accept_local(found: list[local.Local], root: Path, target: Path, options: Options) -> dict[str, str]:
    """Validate, show, confirm, then evaluate the local policies: their code runs only once it is accepted."""
    if not found and not options.trust_local:
        return {}
    if found:
        local.check(root, "validate")
    before = package.accepted(package.read_marker(target))
    accepted = local.confirm(found, local.Trust(before, options.trust_local, options.interactive))
    if found:
        local.check(root, "evals")
    return accepted


def _members(chosen: dict[str, Any], catalog: Path | None, found: list[local.Local]) -> list[Member]:
    """Every member in selection order: catalog entries checked against the catalog, local ones from their snapshots."""
    own = {item.id: Member(item.snapshot, _load_manifest(item.snapshot)) for item in found}
    if catalog is not None:
        clash = sorted(own.keys() & resolve.registry_ids(catalog, chosen["catalog"]["ref"]))
        if clash:
            msg = f"{', '.join(clash)}: a local policy may not reuse a catalog id. {resolve.REFUSED}"
            raise IntegrityError(msg)
        own.update({m.id: m for m in resolve.members(catalog, chosen)})
    return [own[p["id"]] for p in chosen["policies"]]


def install(chosen: dict[str, Any], dest: Path, options: Options) -> tuple[list[package.Label], list[str]]:
    """Trust, fetch, verify, label and build the selection for its client; returns (labels, warnings)."""
    client_id, name = chosen["client"], chosen["bundle"]["name"]
    place.check_owned(client_id, dest, name, options.marketplace)
    target = place.plugin_dir(client_id, dest, name)
    with tempfile.TemporaryDirectory(prefix="chock-install-") as tmp:
        work = Path(tmp)
        root = work / "local"
        found = local.snapshot(chosen, options.base, root)
        accepted = _accept_local(found, root, target, options)
        catalog = _catalog(chosen, options.allowed, work) if "catalog" in chosen else None
        members = _members(chosen, catalog, found)
        repo_root = catalog or root
        labels = package.labels(members, repo_root, client_id, frozenset(accepted))
        grades = {label.policy_id: label.keyword for label in labels}
        context = warnings.Context(
            [m.id for m in members], grades, Path.cwd(), client_id, place.others(client_id, dest, name)
        )
        lines = warnings.warnings_for(context, warnings.load_rules())
        version = f"{chosen['bundle']['version']}+{selection.digest(chosen, accepted)[:12]}"
        if package.client(client_id)["layout"] == place.MARKETPLACE:
            place.migrate_legacy(dest)
        record = package.marker(chosen, accepted)
        package.replace(target, package.stage(members, repo_root, record, version, target))
        place.write_marketplace(client_id, dest, options.marketplace)
    return labels, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chock install",
        description="Build a chock selection into one plugin for one agent",
        # --trust-local accepts custom code: only its exact spelling counts, never an abbreviation.
        allow_abbrev=False,
    )
    parser.add_argument("--selection", required=True, help="chock.selection.yaml, a URL with #s=..., or the bare code")
    parser.add_argument(
        "--client",
        choices=(*CLIENTS, RETIRED),
        metavar="{" + ",".join(CLIENTS) + "}",
        help="The agent to build for (default: the selection's client)",
    )
    parser.add_argument("--dest", help="Install folder (default: the client's own, e.g. ~/.chock/marketplace/<client>)")
    parser.add_argument(
        "--marketplace-name",
        metavar="NAME",
        help=f"Name the build's local marketplace (default: {package.marketplace()}), so a team's own build can use its own",
    )
    parser.add_argument("--apply", action="store_true", help="Also run the client's own install commands, if any")
    parser.add_argument(
        "--allow-source",
        action="append",
        default=[],
        metavar="SOURCE",
        help="Also trust this exact catalog source (the selection itself can never widen trust)",
    )
    parser.add_argument(
        "--trust-local",
        action="append",
        default=[],
        metavar="ID=SHA256",
        help="Accept this local policy at exactly this hash without asking (for scripts, after reading its code)",
    )
    args = parser.parse_args(argv)

    try:
        marketplace = package.marketplace(args.marketplace_name)
        chosen = selection.load(args.selection)
        chosen = {**chosen, "client": args.client or chosen["client"]}
        if chosen["client"] == RETIRED:
            print(
                "chock install: gemini-cli is retired, Antigravity CLI replaces it: use --client antigravity",
                file=sys.stderr,
            )
            return 1
        client_id, name = chosen["client"], chosen["bundle"]["name"]
        dest = (Path(args.dest).expanduser() if args.dest else place.default_dest(client_id)).resolve()
        if "catalog" in chosen:
            print(f"Catalog source: {chosen['catalog']['source']}")
            print(f"Catalog ref:    {chosen['catalog']['ref']}", flush=True)
        options = Options(
            args.allow_source,
            selection.folder(args.selection),
            local.given(args.trust_local),
            local.interactive(),
            marketplace,
        )
        labels, lines = install(chosen, dest, options)
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
        "__MARKETPLACE__": marketplace,
    }
    rendered = steps.render(client_id, tokens)
    _show(rendered, applying=args.apply)
    removal = steps.render_remove(client_id, tokens)
    if removal:
        _print_steps("To remove it:", removal)
    build = claude_plugin.settings()["build_client"]
    build_dest = dest if client_id == build else place.default_dest(build).resolve()
    for line in claude_plugin.lines(client_id, claude_plugin.tokens(build_dest, name, args.selection, marketplace)):
        print(line)
    return _apply(client_id, rendered) if args.apply else 0


if __name__ == "__main__":
    raise SystemExit(main())

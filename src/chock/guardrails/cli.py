"""`chock bundle on|off <policy-id>` and `chock bundle status`: the only writers and the reader of the toggle file."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from chock.guardrails import toggle
from chock.guardrails.plugin import MEMBERS, PROTECT_ID
from chock.install import package, place

EXIT_USAGE = 2
_OLD_BUILD = "label unknown: built by an older chock, re-run chock install"


@dataclass(frozen=True)
class Installed:
    """One chock-built plugin found in a client's default folder."""

    name: str
    client: str
    folder: Path
    members: list[tuple[str, str]]


def _members(folder: Path, marker: dict) -> list[tuple[str, str]]:
    try:
        data = json.loads((folder / MEMBERS).read_text(encoding="utf-8"))
        return [(str(m["id"]), str(m["label"])) for m in data["members"]]
    except (OSError, ValueError, KeyError, TypeError):
        return [(str(p.get("id")), _OLD_BUILD) for p in marker.get("policies", []) if isinstance(p, dict)]


def installed() -> list[Installed]:
    """Every chock-built plugin in each client's own default folder."""
    found = []
    for client_id, data in package.settings()["clients"].items():
        dest = place.default_dest(client_id)
        parent = dest / data["format"] if data["layout"] == place.MARKETPLACE else dest
        if not parent.is_dir():
            continue
        for folder in sorted(p for p in parent.iterdir() if p.is_dir() and not p.name.startswith(".")):
            marker = package.read_marker(folder)
            if marker is not None and marker.get("client") == client_id:
                found.append(Installed(folder.name, client_id, folder, _members(folder, marker)))
    return found


def _scope_path(scope: str | None) -> tuple[Path, str]:
    root = toggle.repo_root(Path.cwd())
    scope = scope or (toggle.REPO if root else toggle.USER)
    if scope == toggle.USER:
        return toggle.user_path(), scope
    if root is None:
        msg = "--scope repo needs a repository here; run it inside one, or use --scope user"
        raise SystemExit(msg)
    return root / toggle.FILENAME, scope


def _bundle_for(policy_id: str, given: str | None, bundles: list[Installed]) -> str:
    if given:
        if not toggle.NAME_RE.fullmatch(given):
            msg = f"bundle name {given!r} must match {toggle.NAME_RE.pattern}"
            raise SystemExit(msg)
        if given not in {b.name for b in bundles}:
            print(f"warning: no installed chock bundle is named {given!r}; the setting waits for one")
        return given
    names = sorted({b.name for b in bundles if policy_id in {i for i, _ in b.members}})
    if len(names) == 1:
        return names[0]
    if not names:
        msg = f"no installed chock bundle carries {policy_id!r}; name it with --bundle <name>"
    else:
        msg = f"{policy_id!r} is in several bundles ({', '.join(names)}); name one with --bundle <name>"
    raise SystemExit(msg)


def _current(path: Path) -> dict[str, dict[str, str]]:
    """The file's toggles before the change; a link, a folder or an invalid file is refused, never overwritten."""
    if not os.path.lexists(path):
        return {}
    if path.is_symlink() or not path.is_file():
        msg = f"{path} is a link or not a regular file; replace it with a plain file first"
        raise SystemExit(msg)
    try:
        return toggle.read(path)
    except toggle.ToggleError as exc:
        msg = f"{path} is invalid, so every guardrail stays on: {exc}. Fix or delete it first."
        raise SystemExit(msg) from exc


def _write(path: Path, toggles: dict[str, dict[str, str]]) -> None:
    document = {"version": toggle.VERSION, "bundles": toggles}
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".guardrails-", suffix=".json", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
    Path(tmp).replace(path)


def switch(policy_id: str, state: str, bundle: str | None, scope: str | None) -> int:
    """Set one member's state in the toggle file of `scope`."""
    if not toggle.NAME_RE.fullmatch(policy_id):
        msg = f"policy id {policy_id!r} must match {toggle.NAME_RE.pattern}"
        raise SystemExit(msg)
    if policy_id == PROTECT_ID:
        msg = f"{PROTECT_ID} is built into every bundle and cannot be switched"
        raise SystemExit(msg)
    name = _bundle_for(policy_id, bundle, installed())
    path, scope = _scope_path(scope)
    toggles = _current(path)
    toggles.setdefault(name, {})[policy_id] = state
    _write(path, toggles)
    print(f"{policy_id} in {name} is now {state} at {scope} scope ({path}).")
    root = toggle.repo_root(Path.cwd())
    if scope == toggle.USER and root is not None and os.path.lexists(root / toggle.FILENAME):
        print(f"note: {root / toggle.FILENAME} governs this repository; the user file applies only outside it.")
    if scope == toggle.REPO and state == toggle.OFF:
        print("Commit it: `chock check --only baseline` reports a policy switched off against the base as a loosening.")
    return 0


def status() -> int:
    """Every installed chock bundle, each member's state where you stand, and its label."""
    path, scope, toggles, warning = toggle.load(Path.cwd())
    print(f"Toggle file: {path} ({scope} scope)" if path else "Toggle file: none, so every member is on")
    if warning:
        print(f"warning: {warning}")
    if scope == toggle.REPO and os.path.lexists(toggle.user_path()):
        print(f"note: {toggle.user_path()} is not read here: the repository governs itself.")
    bundles = installed()
    if not bundles:
        print("No chock bundle is installed in any client's default folder.")
    for item in bundles:
        print(f"\n{item.name} ({item.client}, {item.folder})")
        width = max((len(i) for i, _ in item.members), default=0)
        for policy_id, label in item.members:
            print(f"  {policy_id:{width}}  {toggle.state(toggles, item.name, policy_id):3}  {label}")
    print(f"\n{PROTECT_ID} is built into every bundle and always on.")
    print("Switch one in your own shell: chock bundle off|on <policy-id> [--bundle <name>] [--scope repo|user]")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chock bundle", description="Switch a member of an installed bundle.")
    sub = parser.add_subparsers(dest="action", required=True)
    for state in toggle.STATES:
        one = sub.add_parser(state, help=f"switch one policy {state}")
        one.add_argument("policy_id")
        one.add_argument("--bundle", help="bundle.name; needed when the policy is in several bundles")
        one.add_argument("--scope", choices=(toggle.REPO, toggle.USER), help="default: repo inside one, else user")
    sub.add_parser("status", help="every installed bundle, each member's state and label")
    args = parser.parse_args(argv)
    try:
        if args.action == "status":
            return status()
        return switch(args.policy_id, args.action, args.bundle, args.scope)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(f"chock bundle: {exc.code}", file=sys.stderr)
            return EXIT_USAGE
        raise

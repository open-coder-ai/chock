"""One hook entry per (event, matcher) in a built plugin: its per-policy commands folded into a pinned policy index.

The index sits in the package beside its scripts and names each member by path relative to the plugin root; the
command carries `--root <root text>`, the same form its per-policy commands name the root by, so the package stays a
static file set whatever folder a client installs it in.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from chock.gate import runtime_bundle
from chock.guardrails import plugin as guardrails
from chock.hooks import launch, multi_wiring
from chock.hooks.multi_wiring import Carrier
from chock.plugin.store import SCRIPTS_TEMPLATE

SCRIPTS_DIR = "scripts"
_MEMBER_FLAG = re.compile(r" --member (\S+)")
_NEVER_FOLDED = ("--verify", "--session-start")
_BYTECODE = ("__pycache__",)
_MIN_NAMESPACED_DEPTH = 3


def _package_files(files: dict[Path, str]) -> dict[str, str]:
    """{posix path: sha256 of its bytes} of every file under the package's scripts, bytecode aside."""
    return {
        rel.as_posix(): hashlib.sha256(text.encode("utf-8")).hexdigest()
        for rel, text in files.items()
        if rel.parts[:1] == (SCRIPTS_DIR,) and not set(rel.parts) & set(_BYTECODE)
    }


def _member_files(package: dict[str, str], target: str, shared: set[str]) -> dict[str, str] | None:
    """The files a member is verified by: its own `scripts/<dir>/` in a bundle, else every script beside the runtime."""
    parts = target.split("/")
    if target not in package:
        return None
    if len(parts) >= _MIN_NAMESPACED_DEPTH:
        prefix = "/".join(parts[:2]) + "/"
        return {path: sha for path, sha in package.items() if path.startswith(prefix)}
    index_prefix = multi_wiring.PLUGIN_INDEX_DIR + "/"
    return {path: sha for path, sha in package.items() if path not in shared and not path.startswith(index_prefix)}


def _rooted_paths(argv: list[str]) -> tuple[str, list[str]] | None:
    """(root text, argv with each path made relative to it) when every path names one root and a script, else None."""
    roots, out = set(), []
    for arg in argv:
        if arg.startswith("-"):
            out.append(arg)
            continue
        root, sep, rest = arg.partition(f"/{SCRIPTS_DIR}/")
        if not (root and sep and rest):
            return None
        roots.add(root)
        out.append(f"{SCRIPTS_DIR}/{rest}")
    return (roots.pop(), out) if len(roots) == 1 else None


def _carrier_for(
    agent: str, package: dict[str, str], shared: set[str], bundle: str | None
) -> Any:  # a function (entry) -> Carrier | None
    marker = SCRIPTS_TEMPLATE.format(name=f"{agent}.py")

    def carry(entry: Any) -> Carrier | None:
        if not isinstance(entry, dict):
            return None
        found = multi_wiring.commands(entry)
        command = next(iter(found)) if len(found) == 1 else ""
        split = multi_wiring.split_command(command, marker)
        if split is None or any(flag in split[0].split(" ") for flag in _NEVER_FOLDED):
            return None
        head, argv, quoted = split
        if not multi_wiring.check_fits(agent, entry, argv):
            return None
        rooted = _rooted_paths(argv)
        if rooted is None:
            return None
        files = _member_files(package, rooted[1][1], shared)
        if files is None:
            return None
        if bundle is not None:
            head, member = _bundle_head(head, _MEMBER_FLAG.search(head), agent, bundle)
        else:
            member = None
        return Carrier(entry, command, rooted[1], head, quoted, files, rooted[0], member)

    return carry


def _bundle_head(head: str, found: re.Match[str] | None, agent: str, bundle: str) -> tuple[str, str | None]:
    """A bundle member's head with its toggle wrapper naming every member (`--members`), and the member's id.

    A member with no wrapper (the built-in protection) is wrapped under its own id, which is never toggled.
    """
    if found is None:
        wrapped = guardrails.wrap(f"{head} --guard x", agent, bundle, guardrails.PROTECT_ID)
        head, found = wrapped.removesuffix(" --guard x"), _MEMBER_FLAG.search(wrapped)
        return _MEMBER_FLAG.sub(" --members", head), None
    return _MEMBER_FLAG.sub(" --members", head), found.group(1)


def _shared(agent: str) -> set[str]:
    """The runtime, its shared module and the launcher: every member runs them, none is verified by them."""
    names = {*runtime_bundle.runtime_files(agent), launch.PLUGIN_LAUNCHER}
    return {SCRIPTS_TEMPLATE.format(name=name) for name in names}


def fold_files(
    files: dict[Path, str], hooks_rel: Path | str, agent: str, *, bundle: str | None = None
) -> dict[Path, str]:
    """`files` with the hooks document at `hooks_rel` folded to one entry per (event, matcher), the indexes added.

    A hooks document with no policy entry to fold, or one a vendor's timeout cannot hold, is returned as it is.
    """
    hooks_path = Path(hooks_rel)
    if hooks_path not in files:
        return files
    doc = json.loads(files[hooks_path])
    package = _package_files(files)
    made: dict[Path, str] = {}

    def sink(rel: str, body: bytes) -> None:
        made[Path(rel)] = body.decode("utf-8")

    carry = _carrier_for(agent, package, _shared(agent), bundle)
    folded = _walk(agent, doc, "hooks", carry, sink)
    if not made:
        return files
    out = dict(files)
    out[hooks_path] = json.dumps(folded, indent=2) + "\n"
    out.update(made)
    return out


def _walk(agent: str, node: Any, key: str, carry: Any, sink: Any) -> Any:
    """`node` with every entry list under it folded; `key` names the event for the index file."""
    if isinstance(node, dict):
        return {k: _walk(agent, v, k, carry, sink) for k, v in node.items()}
    if not isinstance(node, list):
        return node
    event = re.sub(r"\W", "_", key)
    placed = multi_wiring.collapse_list(Path(), agent, event, node, set(), write=False, carry=carry, sink=sink)
    return [_walk(agent, item, key, carry, sink) for item in placed]

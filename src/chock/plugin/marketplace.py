"""`chock marketplace` -- emit marketplace index files over a built plugin tree.

A distribution repo serves seven clients from one URL, and what makes that work is a
handful of small index files over one shared `plugins/` tree. This module emits the
Claude-format index, which Claude Code reads at `.claude-plugin/marketplace.json` and
GitHub Copilot CLI reads at `.github/plugin/marketplace.json` -- Copilot's own official
marketplace ships the second as a symlink to the first. We emit two identical files
instead: a symlink would be lost or mangled on Windows checkouts, and two byte-identical
generated files carry the same guarantee with none of the platform dependence.

The index is derived from the plugins' own `.claude-plugin/plugin.json` manifests, which
are themselves derived from `manifest.yaml` -- so nothing here is a second source of
truth, and index drift is caught by `--check` exactly like every other generated surface.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from chock.emit import write_generated

#: Both paths carry identical bytes; see module docstring for why a copy, not a symlink.
INDEX_PATHS = (
    Path(".claude-plugin/marketplace.json"),
    Path(".github/plugin/marketplace.json"),
)

OWNER = {"name": "open-coder-ai", "url": "https://github.com/open-coder-ai"}

#: The index describes the Claude-format tree specifically. `chock plugin build` writes one
#: subtree per format, and only this one carries the hooks these clients read; pointing the
#: index at a shared directory would list packages whose skill text was written for a
#: different client's capabilities.
CLAUDE_TREE = "claude"


def collect_entries(dist_root: Path) -> list[dict[str, Any]]:
    """Index entries from the built plugin manifests, sorted by directory name.

    Sorted so the emitted array never reshuffles between runs -- the index is committed,
    and a reordering diff would bury the real change in every release.
    """
    entries: list[dict[str, Any]] = []
    for manifest_path in sorted(Path(dist_root).glob(f"{CLAUDE_TREE}/*/.claude-plugin/plugin.json")):
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry: dict[str, Any] = {
            "name": data["name"],
            "source": f"./{CLAUDE_TREE}/{manifest_path.parent.parent.name}",
            "description": data.get("description", ""),
        }
        if data.get("version"):
            entry["version"] = data["version"]
        entries.append(entry)
    return entries


#: `claude plugin validate` warns when a marketplace has no description, and the field is
#: what a browsing user reads before deciding to trust the source. It states the two things
#: that matter for that decision: where the content comes from, and that installing a plugin
#: is not the same as adopting Chock in a repository.
DESCRIPTION = (
    "Chock policies packaged as installable plugins. Generated from the chock-catalog; "
    "each plugin states whether it enforces in this client or is advisory."
)


def build_index(dist_root: Path, name: str) -> dict[str, Any]:
    return {
        "name": name,
        "owner": OWNER,
        "description": DESCRIPTION,
        "plugins": collect_entries(dist_root),
    }


def index_differences(dist_root: Path, name: str) -> list[str]:
    """Report where the on-disk index files disagree with the plugin tree."""
    content = json.dumps(build_index(dist_root, name), indent=2) + "\n"
    differences: list[str] = []
    for rel in INDEX_PATHS:
        dest = Path(dist_root) / rel
        if not dest.exists():
            differences.append(f"missing: {rel.as_posix()}")
        elif dest.read_text(encoding="utf-8") != content:
            differences.append(f"differs: {rel.as_posix()}")
    return differences


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chock marketplace",
        description="Emit marketplace index files over a plugin tree built by `chock plugin build`",
    )
    parser.add_argument("action", choices=["build"], help="build: write the index files")
    parser.add_argument("--dist", default=".", help="Distribution root containing plugins/<id>/ directories")
    parser.add_argument("--name", default="chock", help="Marketplace name clients address plugins with")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report index files that are missing or stale, and exit non-zero. Writes nothing.",
    )
    args = parser.parse_args(argv)

    dist_root = Path(args.dist).resolve()
    entries = collect_entries(dist_root)
    if not entries:
        # An empty index is not a valid release: a publish pipeline that finds no plugins
        # has pointed at the wrong tree or run its stages out of order, and emitting an
        # index that delists everything would propagate that mistake to every client.
        print(
            f"No plugin manifests under {dist_root / CLAUDE_TREE}; refusing to write an empty index.", file=sys.stderr
        )
        return 2

    if args.check:
        differences = index_differences(dist_root, args.name)
        if differences:
            print(f"Marketplace index is out of date ({len(differences)} difference(s)):")
            for line in differences:
                print(f"  {line}")
            print("Run `chock marketplace build` and commit the result.")
            return 1
        print(f"Marketplace index matches the plugin tree ({len(entries)} plugins).")
        return 0

    content = json.dumps(build_index(dist_root, args.name), indent=2) + "\n"
    for rel in INDEX_PATHS:
        dest = dist_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_generated(dest, content)
    print(f"Indexed {len(entries)} plugins into {' and '.join(p.as_posix() for p in INDEX_PATHS)}")
    return 0

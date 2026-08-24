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
from chock.lock import compute_pack_hash

OWNER = {"name": "open-coder-ai", "url": "https://github.com/open-coder-ai"}

#: One index per vendor tree: the subtree to walk, its per-plugin manifest path, the
#: index file(s) that vendor's client reads, and the dialect to speak. claude keeps two
#: byte-identical files (see module docstring); codex reuses the claude index shape
#: because Codex reads the legacy `.claude-plugin/marketplace.json` from git
#: marketplaces -- witnessed on a real install, not inferred from docs.
TREES: dict[str, dict[str, Any]] = {
    "claude": {
        "manifest": ".claude-plugin/plugin.json",
        "index_paths": (Path(".claude-plugin/marketplace.json"), Path(".github/plugin/marketplace.json")),
        "style": "claude",
    },
    "codex": {
        "manifest": ".codex-plugin/plugin.json",
        "index_paths": (Path(".claude-plugin/marketplace.json"),),
        "style": "claude",
    },
    "cursor": {
        "manifest": ".cursor-plugin/plugin.json",
        "index_paths": (Path(".cursor-plugin/marketplace.json"),),
        "style": "cursor",
    },
}

#: Kept for callers and tests that predate `--tree`; the default behaviour is unchanged.
CLAUDE_TREE = "claude"
INDEX_PATHS = TREES["claude"]["index_paths"]


def collect_entries(dist_root: Path, tree: str = CLAUDE_TREE) -> list[dict[str, Any]]:
    """Index entries from the built plugin manifests, sorted by directory name.

    Sorted so the emitted array never reshuffles between runs -- the index is committed,
    and a reordering diff would bury the real change in every release.
    """
    manifest_rel = TREES[tree]["manifest"]
    entries: list[dict[str, Any]] = []
    for manifest_path in sorted(Path(dist_root).glob(f"{tree}/*/{manifest_rel}")):
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        package_dir = manifest_path.parent.parent if manifest_rel.count("/") else manifest_path.parent
        entry: dict[str, Any] = {
            "name": data["name"],
            "source": f"./{tree}/{package_dir.name}",
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


def build_index(dist_root: Path, name: str, tree: str = CLAUDE_TREE) -> dict[str, Any]:
    entries = collect_entries(dist_root, tree)
    if TREES[tree]["style"] == "cursor":
        # Cursor's own schema (cursor/plugins, cursor/plugin-template, both verbatim):
        # the description rides under `metadata`, entries carry no version field, and the
        # owner object is name-only -- their examples use {name, email}, so nothing
        # unverified is added.
        return {
            "name": name,
            "owner": {"name": OWNER["name"]},
            "metadata": {"description": DESCRIPTION},
            "plugins": [{k: e[k] for k in ("name", "source", "description")} for e in entries],
        }
    return {
        "name": name,
        "owner": OWNER,
        "description": DESCRIPTION,
        "plugins": entries,
    }


#: Content-addresses the whole release: one sha256 per published plugin directory, over
#: every tree. Clients that can pin (Claude, Copilot, Codex, Grok, Kimi) pin a commit; this
#: is what lets anyone -- an org auditor, a `require_sha` fleet, or the generated-only CI --
#: check that the directory they received is the directory that was published, without
#: trusting the index or the commit history to have been honest about it.
LOCKFILE_NAME = "chock-market.lock"

#: Written explicitly so generated files end with a trailing newline on every platform.
NEWLINE = chr(10)


def build_lock(dist_root: Path) -> dict[str, Any]:
    """Hash every plugin directory in every format tree, sorted for a stable diff.

    Reuses `compute_pack_hash` rather than defining a second hashing rule: two hash
    definitions in one project eventually disagree, and the disagreement surfaces as an
    integrity failure nobody can explain.
    """
    dist_root = Path(dist_root)
    plugins: dict[str, str] = {}
    for manifest in sorted(dist_root.glob("*/*/")):
        if not manifest.is_dir() or manifest.parts[-2].startswith("."):
            continue
        rel = manifest.relative_to(dist_root).as_posix()
        plugins[rel] = compute_pack_hash(manifest)
    return {"lockfile_version": 1, "plugins": plugins}


def lock_differences(dist_root: Path) -> list[str]:
    """Report where the on-disk lockfile disagrees with the tree it describes."""
    content = json.dumps(build_lock(dist_root), indent=2, sort_keys=True) + NEWLINE
    dest = Path(dist_root) / LOCKFILE_NAME
    if not dest.exists():
        return [f"missing: {LOCKFILE_NAME}"]
    return [] if dest.read_text(encoding="utf-8") == content else [f"differs: {LOCKFILE_NAME}"]


#: A page that counts its own contents goes stale the moment a policy is added, and a wrong
#: count in the first thing a user reads is the same class of defect as a wrong coverage
#: claim. So the catalog page is generated outright rather than maintained by hand.
#:
#: It is a file of its own rather than a managed region inside README.md. The repository's
#: rules put README.md off limits to tooling, and honouring that boundary costs nothing
#: here: a dedicated page is a better home for a table that grows with the catalog, and the
#: README can link to it in one static line that never needs updating.
CATALOG_PAGE = "PLUGINS.md"

#: The catalog already publishes a page per policy -- what it is about, what it solves, how
#: it works, and its honest reach. Linking there beats restating it: a second copy of that
#: prose in a generated repo is drift waiting to happen, and the catalog page is the one a
#: reader can check against the policy source.
CATALOG_DOCS = "https://github.com/open-coder-ai/chock-catalog/blob/main/docs"


def _summary(description: str) -> str:
    """First sentence of the description, with the bracketed posture note stripped.

    The posture has its own column and the table is for scanning; the full text is one
    click away on the catalog page.
    """
    text = description.split("[")[0].strip()
    first = text.split(". ")[0].strip().rstrip(".")
    return (first[:96].rstrip() + "...") if len(first) > 99 else first


def render_catalog_page(dist_root: Path, tree: str = CLAUDE_TREE) -> str:
    """The generated catalog: how many packages enforce, how many advise, and which."""
    dist_root = Path(dist_root)
    rows = []
    enforcing = 0
    manifest_rel = TREES[tree]["manifest"]
    for manifest_path in sorted(dist_root.glob(f"{tree}/*/{manifest_rel}")):
        pkg = manifest_path.parent.parent
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        has_hook = (pkg / "hooks" / "hooks.json").exists()
        enforcing += 1 if has_hook else 0
        posture = "enforces" if has_hook else "advisory"
        name = data["name"]
        rows.append(
            f"| [`{name}`]({CATALOG_DOCS}/{name}/README.md) "
            f"| {data.get('version', '-')} | {posture} | {_summary(data.get('description', ''))} |"
        )

    total = len(rows)
    lines = [
        "# Published plugins",
        "",
        "<!-- generated by `chock marketplace build`; edits are overwritten -->",
        "",
        f"**{total} policies are published here: {enforcing} enforce in this client, "
        f"{total - enforcing} are advisory.**",
        "",
        "An enforcing package ships a `PreToolUse` hook, a guard script and a stdlib-only",
        "adapter, and can deny a shell command before the client runs it. It fails open",
        "-- it allows -- when `python3` or a usable `bash` is unavailable. An advisory",
        "package ships skill text the client reads; nothing stops a violation.",
        "",
        "| plugin | version | in this client | what it does |",
        "| :--- | :--- | :--- | :--- |",
        *rows,
        "",
        f"Each name links to its full policy page in the [catalog]({CATALOG_DOCS}): what it",
        "solves, how it works, and its honest reach.",
        "",
    ]
    return NEWLINE.join(lines)


def catalog_page_differences(dist_root: Path, tree: str = CLAUDE_TREE) -> list[str]:
    """Report a catalog page that disagrees with the tree it describes."""
    dest = Path(dist_root) / CATALOG_PAGE
    content = render_catalog_page(dist_root, tree)
    if not dest.exists():
        return [f"missing: {CATALOG_PAGE}"]
    return [] if dest.read_text(encoding="utf-8") == content else [f"differs: {CATALOG_PAGE}"]


def index_differences(dist_root: Path, name: str, tree: str = CLAUDE_TREE) -> list[str]:
    """Report where the on-disk index files disagree with the plugin tree."""
    content = json.dumps(build_index(dist_root, name, tree), indent=2) + "\n"
    differences: list[str] = []
    for rel in TREES[tree]["index_paths"]:
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
        "--tree",
        choices=sorted(TREES),
        default=CLAUDE_TREE,
        help="Which format tree to index; each vendor repo indexes only its own (default: claude)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report index files that are missing or stale, and exit non-zero. Writes nothing.",
    )
    args = parser.parse_args(argv)

    dist_root = Path(args.dist).resolve()
    entries = collect_entries(dist_root, args.tree)
    if not entries:
        # An empty index is not a valid release: a publish pipeline that finds no plugins
        # has pointed at the wrong tree or run its stages out of order, and emitting an
        # index that delists everything would propagate that mistake to every client.
        print(f"No plugin manifests under {dist_root / args.tree}; refusing to write an empty index.", file=sys.stderr)
        return 2

    if args.check:
        differences = (
            index_differences(dist_root, args.name, args.tree)
            + lock_differences(dist_root)
            + catalog_page_differences(dist_root, args.tree)
        )
        if differences:
            print(f"Marketplace index is out of date ({len(differences)} difference(s)):")
            for line in differences:
                print(f"  {line}")
            print("Run `chock marketplace build` and commit the result.")
            return 1
        print(f"Marketplace index matches the plugin tree ({len(entries)} plugins).")
        return 0

    index_paths = TREES[args.tree]["index_paths"]
    content = json.dumps(build_index(dist_root, args.name, args.tree), indent=2) + "\n"
    for rel in index_paths:
        dest = dist_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_generated(dest, content)

    lock = json.dumps(build_lock(dist_root), indent=2, sort_keys=True) + NEWLINE
    write_generated(dist_root / LOCKFILE_NAME, lock)

    write_generated(dist_root / CATALOG_PAGE, render_catalog_page(dist_root, args.tree))

    print(f"Indexed {len(entries)} plugins into {' and '.join(p.as_posix() for p in index_paths)}")
    print(f"Wrote {LOCKFILE_NAME}: sha256 per published plugin directory")
    print(f"Wrote {CATALOG_PAGE}: {len(entries)} plugins with their posture")
    return 0

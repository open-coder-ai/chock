"""`chock marketplace` -- emit marketplace index files over a built plugin tree."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agentseam import packaging

from chock.emit import write_generated
from chock.lock import compute_pack_hash
from chock.vendors import CHOCK_AGENT

OWNER = {"name": "open-coder-ai", "url": "https://github.com/open-coder-ai"}

TREES: dict[str, dict[str, Any]] = {
    "claude": {
        "index_paths": (Path(".claude-plugin/marketplace.json"), Path(".github/plugin/marketplace.json")),
        "style": "claude",
    },
    "codex": {
        "index_paths": (Path(".claude-plugin/marketplace.json"),),
        "style": "claude",
    },
    "cursor": {
        "index_paths": (Path(".cursor-plugin/marketplace.json"),),
        "style": "cursor",
    },
}

CLAUDE_TREE = "claude"
INDEX_PATHS = TREES["claude"]["index_paths"]


def _manifest_rel(tree: str) -> str:
    """This tree's plugin manifest path, from agentseam's packaging layout."""
    return packaging.layout(CHOCK_AGENT[tree])["manifest"]


def collect_entries(dist_root: Path, tree: str = CLAUDE_TREE) -> list[dict[str, Any]]:
    """Index entries from the built plugin manifests, sorted by directory name."""
    manifest_rel = _manifest_rel(tree)
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


DESCRIPTION = (
    "Chock policies packaged as installable plugins. Generated from the chock-catalog; "
    "each plugin states whether it enforces in this client or is advisory."
)


def build_index(dist_root: Path, name: str, tree: str = CLAUDE_TREE) -> dict[str, Any]:
    entries = collect_entries(dist_root, tree)
    if TREES[tree]["style"] == "cursor":
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


LOCKFILE_NAME = "chock-market.lock"

NEWLINE = chr(10)


def build_lock(dist_root: Path) -> dict[str, Any]:
    """Hash every plugin directory in every format tree, sorted for a stable diff."""
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


CATALOG_PAGE = "PLUGINS.md"

CATALOG_DOCS = "https://github.com/open-coder-ai/chock-catalog/blob/main/docs"


def _summary(description: str) -> str:
    """First sentence of the description, with the bracketed posture note stripped."""
    text = description.split("[")[0].strip()
    first = text.split(". ")[0].strip().rstrip(".")
    return (first[:96].rstrip() + "...") if len(first) > 99 else first


def render_catalog_page(dist_root: Path, tree: str = CLAUDE_TREE) -> str:
    """The generated catalog: how many packages enforce, how many advise, and which."""
    dist_root = Path(dist_root)
    rows = []
    enforcing = 0
    manifest_rel = _manifest_rel(tree)
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
        "adapter, and can deny a shell command before the client runs it. It fails open when",
        "`python3` or a usable `bash` is unavailable, and asks -- on Codex CLI, denies -- when",
        "the guard crashes. An advisory package ships skill text; nothing stops a violation.",
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

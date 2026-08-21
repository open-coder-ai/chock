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
import re
import sys
from pathlib import Path
from typing import Any

from chock.emit import write_generated
from chock.lock import compute_pack_hash

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


#: A README that counts its own contents goes stale the moment a policy is added, and a
#: wrong count in the first thing a user reads is the same class of defect as a wrong
#: coverage claim. So the counts and the table are a managed region: generated from the
#: tree, and the generated-only check fails when the file disagrees with what was built.
README_NAME = "README.md"
README_START = "<!-- chock:plugins:start -->"
README_END = "<!-- chock:plugins:end -->"
_README_REGION = re.compile(re.escape(README_START) + r".*?" + re.escape(README_END), re.DOTALL)


#: The catalog already publishes a page per policy -- what it is about, what it solves, how
#: it works, and its honest reach. Linking there beats restating it: a second copy of that
#: prose in a generated repo is drift waiting to happen, and the catalog page is the one a
#: reader can check against the policy source.
CATALOG_DOCS = "https://github.com/open-coder-ai/chock-catalog/blob/main/docs"


def _summary(description: str) -> str:
    """First sentence of the description, with the bracketed posture note stripped.

    The posture already has its own column, and the table is for scanning -- the full text
    is one click away on the catalog page.
    """
    text = description.split("[")[0].strip()
    first = text.split(". ")[0].strip().rstrip(".")
    return (first[:96].rstrip() + "...") if len(first) > 99 else first


def render_readme_block(dist_root: Path) -> str:
    """The generated region: how many packages enforce, how many advise, and which."""
    dist_root = Path(dist_root)
    rows = []
    enforcing = 0
    for manifest_path in sorted(dist_root.glob(f"{CLAUDE_TREE}/*/.claude-plugin/plugin.json")):
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
        README_START,
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
        f"Each name links to its full policy page in the "
        f"[catalog]({CATALOG_DOCS}): what it solves, how it works, and its honest reach.",
        "",
        "<!-- generated by `chock marketplace build`; edits are overwritten -->",
        README_END,
    ]
    return NEWLINE.join(lines)


def apply_readme_block(dist_root: Path) -> str | None:
    """The README with its managed region refreshed, or None when there is no region.

    Absent markers mean the file is not managed -- a distribution repo may reasonably have
    a hand-written README -- so this reports rather than inventing a place to put the block.
    """
    readme = Path(dist_root) / README_NAME
    if not readme.exists():
        return None
    text = readme.read_text(encoding="utf-8")
    if README_START not in text or README_END not in text:
        return None
    return _README_REGION.sub(lambda _m: render_readme_block(dist_root), text, count=1)


def readme_differences(dist_root: Path) -> list[str]:
    """Report a README whose generated region disagrees with the tree it describes."""
    updated = apply_readme_block(dist_root)
    if updated is None:
        return []
    current = (Path(dist_root) / README_NAME).read_text(encoding="utf-8")
    return [] if current == updated else [f"differs: {README_NAME} (generated region)"]


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
        differences = (
            index_differences(dist_root, args.name) + lock_differences(dist_root) + readme_differences(dist_root)
        )
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

    lock = json.dumps(build_lock(dist_root), indent=2, sort_keys=True) + NEWLINE
    write_generated(dist_root / LOCKFILE_NAME, lock)

    updated_readme = apply_readme_block(dist_root)
    if updated_readme is not None:
        write_generated(dist_root / README_NAME, updated_readme)

    print(f"Indexed {len(entries)} plugins into {' and '.join(p.as_posix() for p in INDEX_PATHS)}")
    print(f"Wrote {LOCKFILE_NAME}: sha256 per published plugin directory")
    return 0

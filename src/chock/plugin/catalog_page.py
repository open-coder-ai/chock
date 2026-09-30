"""The generated catalog page: how many packages enforce, which ones, and how each kind does.

Every sentence the page says about an enforcing package is derived from the hooks that package
actually publishes -- a guard's `--guard` command and the events it wires, a gate's `--gate`
command and its own -- so the page cannot describe a mechanism the tree does not ship.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentseam import packaging

from chock import evidence, vendors
from chock.plugin.bundle_grade import _GATE_FLAG, _GUARD_FLAG, ADVISORY, _hook_commands, _hook_events, grade_of
from chock.plugin.bundle_index import read_bundles_index
from chock.plugin.marketplace_core import CLAUDE_TREE, NEWLINE, _manifest_rel
from chock.vendors import CHOCK_AGENT

CATALOG_PAGE = "PLUGINS.md"

CATALOG_DOCS = "https://github.com/open-coder-ai/chock-catalog/blob/main/docs"

#: Summaries longer than this are truncated (at _SUMMARY_TRUNCATE_AT) with an ellipsis.
_SUMMARY_MAX_LEN = 99
_SUMMARY_TRUNCATE_AT = 96


def _summary(description: str) -> str:
    """First sentence of the description, with the bracketed posture note stripped."""
    text = description.split("[", maxsplit=1)[0].strip()
    first = text.split(". ")[0].strip().rstrip(".")
    return (first[:_SUMMARY_TRUNCATE_AT].rstrip() + "...") if len(first) > _SUMMARY_MAX_LEN else first


def _hooks_rel(tree: str) -> str:
    """This tree's hooks-file path, relative to a package directory (root or nested)."""
    return packaging.supports(CHOCK_AGENT[tree], packaging.HOOKS)


#: Per-tree catalog-page vocabulary. Devin gets its own row/summary words and a closing caveat
#: so the page never claims "enforce"/"block" for a fail-open, best-effort client.
_CATALOG_WORDS: dict[str, dict[str, str]] = {
    "devin": {
        "row": "best-effort",
        "summary": "{enforcing} are best-effort in this client, {advisory} are advisory",
        "caveat": (
            "Devin's own docs call plugin hooks fail-open by design -- a hook that fails to load "
            "or run lets the session continue without it -- so none of this is a guarantee."
        ),
    },
}
_DEFAULT_CATALOG_WORDS = {
    "row": "enforces",
    "summary": "{enforcing} enforce in this client, {advisory} are advisory",
    "caveat": "",
}


def _package_kind(hooks_path: Path) -> tuple[str | None, list[str]]:
    """('gate' | 'guard' | None, the events wired) for one published package's hooks file."""
    doc = json.loads(hooks_path.read_text(encoding="utf-8"))
    commands = _hook_commands(doc)
    if any(_GATE_FLAG in command for command in commands):
        return "gate", _hook_events(doc)
    if any(_GUARD_FLAG in command for command in commands):
        return "guard", _hook_events(doc)
    return None, _hook_events(doc)


def _event_list(events: list[str]) -> str:
    """`A`, `A` and `B`, or `A`, `B` and `C`."""
    quoted = [f"`{event}`" for event in events]
    return quoted[0] if len(quoted) == 1 else ", ".join(quoted[:-1]) + " and " + quoted[-1]


def _on_crash(tree: str) -> str:
    """What this client does with a crashed guard's ask, per chock's tested claim for it."""
    row = evidence.claim(CHOCK_AGENT[tree], evidence.HONOURS_ASK)
    if row is None or row.evidence != evidence.TESTED:
        return "returns an ask this client has not been tested to honour"
    if row.honours:
        return "asks for confirmation rather than allowing silently"
    return "refuses the command: this client cannot prompt for confirmation"


def _explain(tree: str, guards: int, guard_events: list[str], gates: int, gate_events: list[str]) -> str:
    """What an enforcing package here ships and does, derived from what was published."""
    parts: list[str] = []
    if guards:
        parts.append(
            f"A guard package ships a guard script and a stdlib-only adapter, hooked at "
            f"{_event_list(guard_events)}, and can deny a shell command before the client runs it. "
            "It fails open when `git` or a usable `bash` is unavailable, and exits 2 when no Python "
            "3.11+ runs. When the guard itself "
            f"crashes, the hook {_on_crash(tree)}."
        )
    if gates:
        judges_write = vendors.pre_tool_event(CHOCK_AGENT[tree]) in gate_events
        reach = (
            "judging the file a write would create and then re-reading what the turn left on disk"
            if judges_write
            else "re-reading what the turn left on disk: this client records no file-writing tool "
            "vocabulary, so the write itself is not judged"
        )
        parts.append(
            f"A gate package ships the policy's gate and a stdlib-only runner instead, hooked at "
            f"{_event_list(gate_events)}, {reach}. It needs `git` and a Python 3.11+; with no working "
            "Python it exits 2, without git a fail-open client allows silently, and a gate that cannot reach a decision refuses rather than allowing "
            "one it never judged."
        )
    parts.append("An advisory package ships skill text; nothing stops a violation.")
    caveat = _CATALOG_WORDS.get(tree, _DEFAULT_CATALOG_WORDS)["caveat"]
    return " ".join(parts + ([caveat] if caveat else []))


def _merge_events(into: list[str], events: list[str]) -> None:
    """Append each event not already listed, keeping first-seen order."""
    into.extend(event for event in events if event not in into)


def _package_grade(pkg: Path, tree: str) -> int:
    """The grade one published package earns from the hooks it ships."""
    hooks = pkg / _hooks_rel(tree)
    gate = pkg / "scripts" / "gate.json"
    hooks_text = hooks.read_text(encoding="utf-8") if hooks.is_file() else None
    gate_text = gate.read_text(encoding="utf-8") if gate.is_file() else None
    return grade_of(hooks_text, gate_text, CHOCK_AGENT[tree])[0]


def _bundle_row(dist_root: Path, tree: str, data: dict[str, Any], members: list[str]) -> str:
    """A bundle's row: its posture is its weakest member's, so it never reads stronger than any of them."""
    words = _CATALOG_WORDS.get(tree, _DEFAULT_CATALOG_WORDS)
    grades = [_package_grade(dist_root / tree / member, tree) for member in members]
    posture = "advisory" if min(grades) == ADVISORY else words["row"]
    name = data["name"]
    listed = ", ".join(f"`{m}`" for m in members)
    return (
        f"| `{name}` | {data.get('version', '-')} | {posture} (weakest member) "
        f"| {_summary(data.get('description', ''))}. Installs {len(members)} policies: {listed} |"
    )


def _bundle_section(bundle_rows: list[str]) -> list[str]:
    """The bundles table, ahead of the policies: install once, and what the set is held to."""
    if not bundle_rows:
        return []
    return [
        "## Bundles",
        "",
        "Install one bundle instead of each policy. A bundle's row takes its weakest member's grade;",
        "each member's own line in its description says what that member does.",
        "",
        "| bundle | version | in this client | what it installs |",
        "| :--- | :--- | :--- | :--- |",
        *bundle_rows,
        "",
        "## Policies",
        "",
    ]


def render_catalog_page(dist_root: Path, tree: str = CLAUDE_TREE) -> str:
    """The generated catalog: how many packages enforce, how many advise, which, and how."""
    dist_root = Path(dist_root)
    words = _CATALOG_WORDS.get(tree, _DEFAULT_CATALOG_WORDS)
    rows = []
    bundle_rows = []
    bundle_members = {b["id"]: b["members"] for b in read_bundles_index(dist_root)}
    enforcing = guards = gates = 0
    guard_events: list[str] = []
    gate_events: list[str] = []
    manifest_rel = _manifest_rel(tree)
    hooks_rel = _hooks_rel(tree)
    for manifest_path in sorted(dist_root.glob(f"{tree}/*/{manifest_rel}")):
        pkg = manifest_path.parent.parent
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if data["name"] in bundle_members:
            bundle_rows.append(_bundle_row(dist_root, tree, data, bundle_members[data["name"]]))
            continue
        hooks_path = pkg / hooks_rel
        has_hook = hooks_path.exists()
        if has_hook:
            enforcing += 1
            kind, events = _package_kind(hooks_path)
            if kind == "gate":
                gates += 1
                _merge_events(gate_events, events)
            elif kind == "guard":
                guards += 1
                _merge_events(guard_events, events)
        posture = words["row"] if has_hook else "advisory"
        name = data["name"]
        rows.append(
            f"| [`{name}`]({CATALOG_DOCS}/{name}/README.md) "
            f"| {data.get('version', '-')} | {posture} | {_summary(data.get('description', ''))} |"
        )

    total = len(rows)
    summary = words["summary"].format(enforcing=enforcing, advisory=total - enforcing)
    lines = [
        "# Published plugins",
        "",
        "<!-- generated by `chock marketplace build`; edits are overwritten -->",
        "",
        f"**{total} policies are published here: {summary}.**",
        "",
        _explain(tree, guards, guard_events, gates, gate_events),
        "",
        *_bundle_section(bundle_rows),
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

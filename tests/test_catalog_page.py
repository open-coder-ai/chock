"""The catalog page describes each kind of enforcing package from what that package publishes."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from chock.plugin import catalog_page
from chock.plugin.cli import main as plugin_main
from chock.plugin.marketplace import CATALOG_PAGE
from chock.plugin.marketplace import main as marketplace_main

GUARD_MANIFEST = {
    "id": "block-destructive-commands",
    "name": "Block Destructive Commands",
    "version": "0.0.2",
    "description": "Block rm -rf and friends before they run.",
    "artifact": "hook",
    "enforcement": "block",
}
ADVISORY_MANIFEST = {
    "id": "code-safety",
    "name": "Code Safety Rule",
    "version": "0.0.1",
    "description": "Advisory rule with no gate.",
    "artifact": "rule",
    "enforcement": "advise",
    "rule": {"text": "never(commit): secrets"},
}

GATE_MANIFEST = {
    "id": "no-todo",
    "name": "No TODO",
    "version": "0.0.1",
    "description": "Refuse a TODO as it is written.",
    "artifact": "hook",
    "enforcement": "block",
    "hook": {
        "gate": {
            "kind": "content_regex",
            "on": ["commit", "tool_use"],
            "action": "block",
            "message": "TODO added.",
            "params": {"content_pattern": "TODO"},
        }
    },
}


@pytest.fixture
def gate_dist(tmp_path: Path) -> Path:
    """A built tree holding one guard, one gate and one advisory policy."""
    for manifest in [GUARD_MANIFEST, ADVISORY_MANIFEST, GATE_MANIFEST]:
        pack = tmp_path / ".agents" / "policies" / manifest["id"]
        pack.mkdir(parents=True)
        (pack / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
        if manifest["id"] == "block-destructive-commands":
            impl = pack / "implementations"
            impl.mkdir()
            (impl / f"{manifest['id']}.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    out = tmp_path / "dist"
    assert plugin_main(["build", "--repo", str(tmp_path), "--format", "all", "--out-dir", str(out)]) == 0
    return out


def test_catalog_page_tells_a_gate_from_a_guard(gate_dist: Path) -> None:
    """A gate judges what a turn writes; the page must not call it a shell-command guard."""
    marketplace_main(["build", "--dist", str(gate_dist)])
    body = (gate_dist / CATALOG_PAGE).read_text(encoding="utf-8")

    assert "3 policies are published here: 2 enforce in this client, 1 are advisory." in body
    assert "A guard package ships a guard script and a stdlib-only adapter, hooked at `PreToolUse`" in body
    assert (
        "A gate package ships the policy's gate and a stdlib-only runner instead, hooked at `PreToolUse` and `Stop`"
        in body
    )
    assert "judging the file a write would create" in body
    assert "refuses rather than allowing one it never judged" in body


def test_catalog_page_says_when_a_client_cannot_judge_the_write() -> None:
    """A gate published at the turn's end only says so; no page tree is stop-only since agentseam 0.3.4."""
    body = catalog_page._explain("codex", 0, [], 1, ["Stop"])

    assert "hooked at `Stop`, re-reading what the turn left on disk" in body
    assert "so the write itself is not judged" in body
    assert "judging the file a write would create" not in body


def test_catalog_page_says_codex_judges_the_write(gate_dist: Path) -> None:
    """agentseam 0.3.4 records `apply_patch` as Codex's write tool, so its gate runs before the write too."""
    marketplace_main(["build", "--dist", str(gate_dist), "--tree", "codex"])
    body = (gate_dist / CATALOG_PAGE).read_text(encoding="utf-8")

    assert "hooked at `PreToolUse` and `Stop`, judging the file a write would create" in body
    assert "so the write itself is not judged" not in body


def test_catalog_page_names_each_client_s_own_events(gate_dist: Path) -> None:
    """The events on the page are the ones the published hooks wire, in that client's spelling."""
    marketplace_main(["build", "--dist", str(gate_dist), "--tree", "cursor"])
    body = (gate_dist / CATALOG_PAGE).read_text(encoding="utf-8")

    assert "hooked at `beforeShellExecution`" in body
    assert "hooked at `preToolUse` and `stop`" in body
    assert "`PreToolUse`" not in body


@pytest.mark.parametrize(
    ("tree", "on_crash"),
    [
        ("claude", "the hook asks for confirmation rather than allowing silently."),
        ("cursor", "the hook asks for confirmation rather than allowing silently."),
        ("codex", "the hook refuses the command: this client cannot prompt for confirmation."),
    ],
)
def test_catalog_page_states_this_client_s_own_crash_answer(gate_dist: Path, tree: str, on_crash: str) -> None:
    """A crashed guard's answer comes from the tested claim for this client, not another's."""
    marketplace_main(["build", "--dist", str(gate_dist), "--tree", tree])
    body = (gate_dist / CATALOG_PAGE).read_text(encoding="utf-8")

    assert f"When the guard itself crashes, {on_crash}" in body
    assert "Codex CLI" not in body

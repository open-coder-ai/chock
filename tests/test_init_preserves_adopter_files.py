"""Re-running `init` must never silently destroy what the adopter wrote."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import init_repo

from chock.scaffold.agents_md import POINTER_START
from chock.scaffold.init import cmd_init

CUSTOM = "\n## Team conventions\n\nnever_deploy(on: friday)\n"


def _init(repo: Path, *extra: str) -> int:
    return cmd_init([str(repo), "--skip-hooks", *extra])


@pytest.fixture
def onboarded(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path)
    assert _init(repo) == 0
    return repo


def _append(path: Path, text: str = CUSTOM) -> str:
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")
    return path.read_text(encoding="utf-8")


def test_agents_md_edits_survive_a_second_init(onboarded: Path) -> None:
    agents_md = onboarded / "AGENTS.md"
    _append(agents_md)

    assert _init(onboarded) == 0

    after = agents_md.read_text(encoding="utf-8")
    assert "never_deploy(on: friday)" in after, "init destroyed adopter content in AGENTS.md"
    assert POINTER_START in after, "the managed pointer block must still be maintained"


def test_content_outside_the_marker_survives_a_second_init(onboarded: Path) -> None:
    """The default agent set (claude, copilot, gemini) resolves to one dedicated file,"""
    claude_md = onboarded / "CLAUDE.md"
    before = _append(claude_md)

    assert _init(onboarded) == 0

    after = claude_md.read_text(encoding="utf-8")
    assert after.startswith(before), "content outside the marker block was disturbed"


def test_a_deselected_wrapper_with_edits_is_not_deleted(tmp_path: Path) -> None:
    """Deleting a file the adopter added content to destroys it as surely as overwriting it."""
    repo = init_repo(tmp_path)
    assert _init(repo, "--agents", "grok") == 0
    grok_md = repo / ".grok" / "GROK.md"
    _append(grok_md)

    assert _init(repo, "--agents", "claude") == 0

    assert grok_md.exists(), "init deleted an adopter-edited wrapper"
    after = grok_md.read_text(encoding="utf-8")
    assert "never_deploy(on: friday)" in after, "the adopter's own content was deleted along with chock's block"
    assert "Authoritative rules and conventions" not in after, "chock's block should be gone once grok is deselected"


def test_a_wrapper_with_no_adopter_content_is_deleted_on_deselect(tmp_path: Path) -> None:
    """The mirror case: nothing but chock's own block is an orphan, not adopter content."""
    repo = init_repo(tmp_path)
    assert _init(repo, "--agents", "grok") == 0
    grok_md = repo / ".grok" / "GROK.md"
    assert grok_md.exists()

    assert _init(repo, "--agents", "claude") == 0

    assert not grok_md.exists(), "an orphaned wrapper with no adopter content was left behind"
    assert not grok_md.parent.exists(), "its now-empty parent directory was left behind"


def test_the_marker_region_is_refreshed_with_no_force_needed(onboarded: Path) -> None:
    """A managed region is not a whole file: there is nothing to preserve-then-force"""
    from agentseam.instructions import BEGIN, END

    claude_md = onboarded / "CLAUDE.md"
    text = claude_md.read_text(encoding="utf-8")
    assert BEGIN in text and END in text
    head = text.split(BEGIN, 1)[0]
    tail = text.split(END, 1)[1]
    claude_md.write_text(head + BEGIN + "\nstale content from an older version\n" + END + tail, encoding="utf-8")

    assert _init(onboarded) == 0

    after = claude_md.read_text(encoding="utf-8")
    assert "stale content from an older version" not in after
    assert "Authoritative rules and conventions" in after


def test_an_untouched_repo_is_byte_identical_after_a_rerun(onboarded: Path) -> None:
    """Preservation must not come at the cost of refreshing files nobody touched."""
    tracked = ["AGENTS.md", "CLAUDE.md", "docs/README.md"]
    before = {rel: (onboarded / rel).read_bytes() for rel in tracked}

    assert _init(onboarded) == 0

    assert {rel: (onboarded / rel).read_bytes() for rel in tracked} == before
    assert not (onboarded / ".github" / "copilot-instructions.md").exists(), (
        "copilot reads AGENTS.md natively and must get no dedicated file"
    )

"""Re-running `init` must never silently destroy what the adopter wrote.

`init` is not a one-shot command -- it is re-run after adding a policy and after every
upgrade. It used to rewrite every scaffolded file unconditionally, so an edit to `AGENTS.md`
(the file this framework calls the single source of truth and tells adopters to own) or to
`.claude/CLAUDE.md` was gone, while the command printed "Initialized Chock" and
exited 0. Silent data loss inside the command that establishes trust in the tool.

Per-agent instruction files moved to agentseam's marker-block model (owner decision #8,
`scaffold/adapters.py`): chock never again claims a whole file, only a delimited region
inside one, so most of the cases below now assert coexistence -- the adopter's own content
survives OUTSIDE the marker, unconditionally, while chock's own block INSIDE it is always
kept current, unconditionally, with no `--force` escape hatch needed for either half.
"""

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


# --------------------------------------------------------------- adopter content survives
def test_agents_md_edits_survive_a_second_init(onboarded: Path) -> None:
    agents_md = onboarded / "AGENTS.md"
    _append(agents_md)

    assert _init(onboarded) == 0

    after = agents_md.read_text(encoding="utf-8")
    assert "never_deploy(on: friday)" in after, "init destroyed adopter content in AGENTS.md"
    assert POINTER_START in after, "the managed pointer block must still be maintained"


def test_content_outside_the_marker_survives_a_second_init(onboarded: Path) -> None:
    """The default agent set (claude, copilot, gemini) resolves to one dedicated file,
    `CLAUDE.md` at the repo root -- copilot and gemini both read AGENTS.md natively
    (agentseam.instructions.reads_shared) and get none. Content the adopter adds outside
    chock's marker block must survive exactly like it does in AGENTS.md itself."""
    claude_md = onboarded / "CLAUDE.md"
    before = _append(claude_md)

    assert _init(onboarded) == 0

    after = claude_md.read_text(encoding="utf-8")
    assert after.startswith(before), "content outside the marker block was disturbed"


def test_a_deselected_wrapper_with_edits_is_not_deleted(tmp_path: Path) -> None:
    """Deleting a file the adopter added content to destroys it as surely as overwriting it.

    grok does not read AGENTS.md natively, so selecting it gets a dedicated marker-block
    file (`.grok/GROK.md`). Deselecting it again correctly strips chock's own block (grok
    is no longer selected, so chock no longer owns any of this file) -- but must not take
    the adopter's own content, appended outside that block, down with it.
    """
    repo = init_repo(tmp_path)
    assert _init(repo, "--agents", "grok") == 0
    grok_md = repo / ".grok" / "GROK.md"
    _append(grok_md)

    assert _init(repo, "--agents", "claude") == 0  # explicitly deselects grok

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

    assert _init(repo, "--agents", "claude") == 0  # explicitly deselects grok

    assert not grok_md.exists(), "an orphaned wrapper with no adopter content was left behind"
    assert not grok_md.parent.exists(), "its now-empty parent directory was left behind"


# --------------------------------------------------- the marker region is always current
def test_the_marker_region_is_refreshed_with_no_force_needed(onboarded: Path) -> None:
    """A managed region is not a whole file: there is nothing to preserve-then-force
    inside it, since it is never the adopter's to begin with -- only what surrounds it is.
    Hand-editing inside the markers (simulating drift, or an older chock version's text)
    is silently corrected on the very next `init`, same as `agents_md.render_agents_md`
    already does for AGENTS.md's own pointer block.
    """
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


# -------------------------------------------------------------------- idempotency preserved
def test_an_untouched_repo_is_byte_identical_after_a_rerun(onboarded: Path) -> None:
    """Preservation must not come at the cost of refreshing files nobody touched."""
    tracked = ["AGENTS.md", "CLAUDE.md", "docs/README.md"]
    before = {rel: (onboarded / rel).read_bytes() for rel in tracked}

    assert _init(onboarded) == 0

    assert {rel: (onboarded / rel).read_bytes() for rel in tracked} == before
    assert not (onboarded / ".github" / "copilot-instructions.md").exists(), (
        "copilot reads AGENTS.md natively and must get no dedicated file"
    )

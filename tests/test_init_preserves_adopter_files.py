"""Re-running `init` must never silently destroy what the adopter wrote.

`init` is not a one-shot command -- it is re-run after adding a policy and after every
upgrade. It used to rewrite every scaffolded file unconditionally, so an edit to `AGENTS.md`
(the file this framework calls the single source of truth and tells adopters to own) or to
`.claude/CLAUDE.md` was gone, while the command printed "Initialized Chock" and
exited 0. Silent data loss inside the command that establishes trust in the tool.
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


def test_adapter_edits_survive_a_second_init(onboarded: Path) -> None:
    claude_md = onboarded / ".claude" / "CLAUDE.md"
    before = _append(claude_md)

    assert _init(onboarded) == 0

    assert claude_md.read_text(encoding="utf-8") == before


def test_a_preserved_file_is_reported_not_silently_skipped(onboarded: Path, capsys: pytest.CaptureFixture) -> None:
    """A silent skip is the same lie as a silent overwrite, pointed the other way."""
    _append(onboarded / ".claude" / "CLAUDE.md")
    capsys.readouterr()

    assert _init(onboarded) == 0

    assert ".claude/CLAUDE.md" in capsys.readouterr().out


def test_a_deselected_wrapper_with_edits_is_not_deleted(tmp_path: Path) -> None:
    """Deleting an edited wrapper destroys adopter content as surely as overwriting it."""
    repo = init_repo(tmp_path)
    assert _init(repo, "--agents", "cursor") == 0
    cursorrules = repo / ".cursorrules"
    before = _append(cursorrules)

    assert _init(repo) == 0  # default agent set no longer includes cursor

    assert cursorrules.exists(), "init deleted an adopter-edited wrapper"
    assert cursorrules.read_text(encoding="utf-8") == before


# ------------------------------------------------------------------- the escape hatch works
def test_force_overwrites_a_modified_file(onboarded: Path) -> None:
    """Preserving by default is only honest if there is a stated way to opt out."""
    claude_md = onboarded / ".claude" / "CLAUDE.md"
    _append(claude_md)

    assert _init(onboarded, "--force") == 0

    assert "never_deploy(on: friday)" not in claude_md.read_text(encoding="utf-8")


# -------------------------------------------------------------------- idempotency preserved
def test_an_untouched_repo_is_byte_identical_after_a_rerun(onboarded: Path) -> None:
    """Preservation must not come at the cost of refreshing files nobody touched.

    Guards the guard: a `_preserve_or_write` that never writes would pass every test above.
    """
    tracked = ["AGENTS.md", ".claude/CLAUDE.md", ".github/copilot-instructions.md", "docs/README.md"]
    before = {rel: (onboarded / rel).read_bytes() for rel in tracked}

    assert _init(onboarded) == 0

    assert {rel: (onboarded / rel).read_bytes() for rel in tracked} == before


def test_content_from_an_older_template_is_kept_until_forced(onboarded: Path) -> None:
    """The stated trade-off, asserted rather than assumed.

    Content the adopter never typed but that no longer matches the current template is
    indistinguishable from an edit, so it is kept and reported -- an upgrade does not
    silently refresh it. `--force` is the documented way to take the new template.
    """
    claude_md = onboarded / ".claude" / "CLAUDE.md"
    fresh = claude_md.read_text(encoding="utf-8")
    claude_md.write_text("content from an older version\n", encoding="utf-8")

    assert _init(onboarded) == 0
    assert claude_md.read_text(encoding="utf-8") != fresh

    assert _init(onboarded, "--force") == 0
    assert claude_md.read_text(encoding="utf-8") == fresh

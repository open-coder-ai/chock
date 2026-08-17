"""The installer must not treat its own dispatcher as a foreign hook.

Following the documented quickstart -- `chock init .` then `chock sync --repo .`
-- installed the dispatcher twice. The second run found a `pre-commit` already in place, did not
recognise it as its own, and relocated it to `pre-commit.d/00-preexisting`.

The copy is inert: it globs `$HOOK_DIR/pre-commit.d/` resolved from *its own* location inside
`pre-commit.d/`, so it looks for `pre-commit.d/pre-commit.d/` and finds nothing. Nothing broke.
But every adopter following the quickstart got the file, and it was visible in the catalog's
README transcript -- a tool that appears confused about its own output invites doubt about the
parts that are not cosmetic.

The asymmetry in `_is_ours` is the part worth protecting. Getting it wrong in the direction of
"assume ours" deletes hooks people wrote.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from chock.hooks.install import (
    DISPATCHER_TEMPLATE,
    GENERATED_MARKER,
    install_dispatcher,
    relocate_existing_hook,
)

FOREIGN = "#!/bin/sh\n# husky or whatever the adopter already had\nexit 0\n"


@pytest.fixture
def hooks_dir(tmp_path: Path) -> Path:
    d = tmp_path / "hooks"
    d.mkdir()
    return d


def test_the_marker_reaches_the_rendered_dispatcher() -> None:
    """`_is_ours` is only meaningful if what we write carries what we look for."""
    assert GENERATED_MARKER in DISPATCHER_TEMPLATE.format(event="pre-commit", marker=GENERATED_MARKER)


def test_installing_twice_leaves_no_00_preexisting(hooks_dir: Path) -> None:
    """The quickstart is `init` then `install-hooks`, so this path is the common one."""
    install_dispatcher(hooks_dir, "pre-commit")
    install_dispatcher(hooks_dir, "pre-commit")

    assert not (hooks_dir / "pre-commit.d" / "00-preexisting").exists()
    assert GENERATED_MARKER in (hooks_dir / "pre-commit").read_text(encoding="utf-8")


def test_a_foreign_hook_is_still_preserved(hooks_dir: Path) -> None:
    """The regression that matters: not relocating a real hook destroys it.

    `install_dispatcher` overwrites the hook path unconditionally, so a foreign hook that is
    not moved aside first is simply gone.
    """
    (hooks_dir / "pre-commit").write_text(FOREIGN, encoding="utf-8")

    install_dispatcher(hooks_dir, "pre-commit")

    relocated = hooks_dir / "pre-commit.d" / "00-preexisting"
    assert relocated.read_text(encoding="utf-8") == FOREIGN
    # NTFS has no Unix execute bit: stat() reports 0o666 regardless of any chmod, so the
    # permission half of this test is only meaningful where the bit exists. The content
    # assertion above -- the half that protects adopters' hooks -- runs everywhere.
    if os.name != "nt":
        assert relocated.stat().st_mode & stat.S_IXUSR, "a relocated hook must stay executable"


def test_an_unreadable_hook_is_preserved_rather_than_assumed_ours(hooks_dir: Path) -> None:
    """Undecodable bytes must answer "not ours".

    A compiled or non-UTF-8 hook cannot be checked for the marker. Preserving it costs an inert
    `00-preexisting`; assuming it is ours deletes an adopter's hook, so the failure has to fall
    on the recoverable side.
    """
    hook = hooks_dir / "pre-commit"
    hook.write_bytes(b"\x7fELF\x02\x01\x01\x00 binary hook \xff\xfe")

    install_dispatcher(hooks_dir, "pre-commit")

    assert (hooks_dir / "pre-commit.d" / "00-preexisting").read_bytes().startswith(b"\x7fELF")


def test_an_existing_stale_copy_is_cleaned_up(hooks_dir: Path) -> None:
    """Repos already carrying the artefact get repaired, not just spared.

    The bug shipped, so preventing new copies is only half the fix -- adopters who already ran
    the quickstart have the file and no reason to know it is inert.
    """
    impl = hooks_dir / "pre-commit.d"
    impl.mkdir()
    (impl / "00-preexisting").write_text(
        DISPATCHER_TEMPLATE.format(event="pre-commit", marker=GENERATED_MARKER), encoding="utf-8"
    )

    install_dispatcher(hooks_dir, "pre-commit")

    assert not (impl / "00-preexisting").exists()


def test_cleanup_never_removes_a_real_relocated_hook(hooks_dir: Path) -> None:
    """A genuine `00-preexisting` must survive every subsequent install.

    Relocation happens once, on the install that found a foreign hook. Every later run sees the
    relocated copy sitting in `pre-commit.d/` and must leave it alone -- deleting it would mean
    the installer eventually eats the hook it promised to chain to.
    """
    (hooks_dir / "pre-commit").write_text(FOREIGN, encoding="utf-8")
    install_dispatcher(hooks_dir, "pre-commit")
    install_dispatcher(hooks_dir, "pre-commit")
    install_dispatcher(hooks_dir, "pre-commit")

    assert (hooks_dir / "pre-commit.d" / "00-preexisting").read_text(encoding="utf-8") == FOREIGN


def test_relocate_is_a_no_op_when_nothing_is_there(hooks_dir: Path) -> None:
    (hooks_dir / "pre-commit.d").mkdir()
    relocate_existing_hook(hooks_dir / "pre-commit", hooks_dir / "pre-commit.d")
    assert not (hooks_dir / "pre-commit.d" / "00-preexisting").exists()

"""The installer must not treat its own dispatcher as a foreign hook."""

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
    """The regression that matters: not relocating a real hook destroys it."""
    (hooks_dir / "pre-commit").write_text(FOREIGN, encoding="utf-8")

    install_dispatcher(hooks_dir, "pre-commit")

    relocated = hooks_dir / "pre-commit.d" / "00-preexisting"
    assert relocated.read_text(encoding="utf-8") == FOREIGN
    if os.name != "nt":
        assert relocated.stat().st_mode & stat.S_IXUSR, "a relocated hook must stay executable"


def test_an_unreadable_hook_is_preserved_rather_than_assumed_ours(hooks_dir: Path) -> None:
    """Undecodable bytes must answer "not ours"."""
    hook = hooks_dir / "pre-commit"
    hook.write_bytes(b"\x7fELF\x02\x01\x01\x00 binary hook \xff\xfe")

    install_dispatcher(hooks_dir, "pre-commit")

    assert (hooks_dir / "pre-commit.d" / "00-preexisting").read_bytes().startswith(b"\x7fELF")


def test_an_existing_stale_copy_is_cleaned_up(hooks_dir: Path) -> None:
    """Repos already carrying the artefact get repaired, not just spared."""
    impl = hooks_dir / "pre-commit.d"
    impl.mkdir()
    (impl / "00-preexisting").write_text(
        DISPATCHER_TEMPLATE.format(event="pre-commit", marker=GENERATED_MARKER), encoding="utf-8"
    )

    install_dispatcher(hooks_dir, "pre-commit")

    assert not (impl / "00-preexisting").exists()


def test_cleanup_never_removes_a_real_relocated_hook(hooks_dir: Path) -> None:
    """A genuine `00-preexisting` must survive every subsequent install."""
    (hooks_dir / "pre-commit").write_text(FOREIGN, encoding="utf-8")
    install_dispatcher(hooks_dir, "pre-commit")
    install_dispatcher(hooks_dir, "pre-commit")
    install_dispatcher(hooks_dir, "pre-commit")

    assert (hooks_dir / "pre-commit.d" / "00-preexisting").read_text(encoding="utf-8") == FOREIGN


def test_relocate_is_a_no_op_when_nothing_is_there(hooks_dir: Path) -> None:
    (hooks_dir / "pre-commit.d").mkdir()
    relocate_existing_hook(hooks_dir / "pre-commit", hooks_dir / "pre-commit.d")
    assert not (hooks_dir / "pre-commit.d" / "00-preexisting").exists()

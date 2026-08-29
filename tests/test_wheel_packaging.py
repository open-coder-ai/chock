"""The built wheel must contain the complete packaged template tree.

setuptools' `**/*` does not match dot-directories, so all 42 files under
`chock-init/assets/templates/` -- `.chock/`, `.agents/`, `.claude/`, and the
adapter dotfiles -- were absent from every built wheel. Nothing failed, because nothing
read them: `init` carried its own inline copies. The gap surfaced only when `init` started
reading one packaged file.

`test_wheel_install.py` catches this indirectly, via whichever file `init` happens to read.
That is one file's worth of coverage for a 42-file tree, and it would go quiet again the
moment `init` stopped reading that particular file. This asserts the tree itself.
"""

from __future__ import annotations

import contextlib
import zipfile
from pathlib import Path

import pytest

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = FRAMEWORK_ROOT / "src" / "chock" / "packs" / "_skills" / "chock-init" / "assets" / "templates"


def _source_template_files() -> set[str]:
    return {p.relative_to(TEMPLATE_ROOT).as_posix() for p in TEMPLATE_ROOT.rglob("*") if p.is_file()}


@pytest.fixture(scope="module")
def wheel_names(built_wheel: Path) -> set[str]:
    """Entry names in the shared session wheel."""
    return set(zipfile.ZipFile(built_wheel).namelist())


def test_wheel_contains_every_packaged_template(wheel_names: set[str]) -> None:
    """Every template file on disk must also be in the wheel -- no silent subset."""
    prefix = "chock/packs/_skills/chock-init/assets/templates/"
    in_wheel = {n[len(prefix) :] for n in wheel_names if n.startswith(prefix)}
    missing = sorted(_source_template_files() - in_wheel)
    assert not missing, f"{len(missing)} template file(s) missing from the wheel: {missing[:10]}"


def test_wheel_contains_the_dot_directory_tree(wheel_names: set[str]) -> None:
    """The specific class that vanished: paths containing a dot-directory.

    Kept separate from the parity test above so a regression names the actual cause
    rather than reporting a generic count mismatch.
    """
    dot_files = {f for f in _source_template_files() if any(part.startswith(".") for part in Path(f).parts)}
    assert dot_files, "expected dot-directory templates in the source tree"

    prefix = "chock/packs/_skills/chock-init/assets/templates/"
    in_wheel = {n[len(prefix) :] for n in wheel_names if n.startswith(prefix)}
    missing = sorted(dot_files - in_wheel)
    assert not missing, (
        f"{len(missing)} of {len(dot_files)} dot-directory templates missing from the wheel. "
        f"setuptools `**/*` does not match dotfiles; package-data needs explicit dot patterns. "
        f"Missing: {missing[:10]}"
    )


def test_no_inline_duplicate_of_a_packaged_template() -> None:
    """Guard the mechanism that hid the packaging gap, not just the gap itself.

    An inline copy of a packaged asset keeps working when the packaged one is missing, so
    the absence stays invisible. This was a two-file spot check while 24 of the 26 packaged
    templates were still assembled from inline constants -- and `AGENTS.md` had already
    drifted 962 bytes from its packaged copy, the copy `references/templates.md` tells an
    agent is the catalog of generated output.

    Now every adapter template is read, so the audit is over the whole set.
    """
    import chock.scaffold.init as init

    # Per-agent instruction files no longer come from a packaged template at all: the
    # marker-block model (agentseam.instructions, see scaffold/adapters.py) writes chock's
    # own POINTER_TEXT constant, and agentseam decides the path (or no file, for an agent
    # that reads AGENTS.md natively). Aider is the one exception -- its `.aider.conf.yml`
    # is a real config file agentseam's module cannot express, so chock still ships it as a
    # packaged template.
    read_verbatim = {
        "docs/README.md",
        ".chock/dependency-allowlist.txt",
        "AGENTS.md",
        ".chock/config.yaml",
        ".aider.conf.yml",
    }
    for rel in sorted(read_verbatim):
        assert (TEMPLATE_ROOT / rel).exists(), f"packaged template {rel} is missing"
        # Reading through the helper is what makes a missing packaged file fail loudly.
        assert init.packaged_template(rel), f"{rel} read back empty"


def test_every_adapter_file_is_read_from_its_template(tmp_path: Path) -> None:
    """`init` must READ each adapter template, not assemble equivalent content.

    Asserting "output equals template" would be vacuous now that one is generated from the
    other -- a break-and-restore proved it: editing the template changed both sides and the
    comparison still passed. So this removes the template instead. If `init` genuinely reads
    it, generation fails; if a future change reintroduces an inline copy, it silently
    succeeds and this test fails, which is the regression worth catching.
    """
    from chock.scaffold.adapters import write_instructions

    repo = tmp_path / "aider_conf"
    repo.mkdir(parents=True)
    with pytest.raises((FileNotFoundError, OSError)):
        with _template_hidden(".aider.conf.yml"):
            write_instructions(repo, ["aider"])


@contextlib.contextmanager
def _template_hidden(rel: str):
    """Temporarily remove a packaged template, restoring it whatever happens."""
    path = TEMPLATE_ROOT / rel
    saved = path.read_bytes()
    path.unlink()
    try:
        yield
    finally:
        path.write_bytes(saved)

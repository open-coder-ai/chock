"""The built wheel must contain the complete packaged template tree."""

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
    """The specific class that vanished: paths containing a dot-directory."""
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
    """Guard the mechanism that hid the packaging gap, not just the gap itself."""
    import chock.scaffold.init as init

    read_verbatim = {
        "docs/README.md",
        ".chock/dependency-allowlist.txt",
        "AGENTS.md",
        ".chock/config.yaml",
        ".aider.conf.yml",
    }
    for rel in sorted(read_verbatim):
        assert (TEMPLATE_ROOT / rel).exists(), f"packaged template {rel} is missing"
        assert init.packaged_template(rel), f"{rel} read back empty"


def test_every_adapter_file_is_read_from_its_template(tmp_path: Path) -> None:
    """`init` must READ each adapter template, not assemble equivalent content."""
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

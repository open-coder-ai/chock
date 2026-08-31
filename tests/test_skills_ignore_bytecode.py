"""Bytecode inside the shipped skill tree is not skill content."""

from __future__ import annotations

import compileall
from pathlib import Path

import pytest

from chock.scaffold.skills import differences, install_skills, shipped_root

TEMPLATE = Path("policy-init") / "assets" / "templates" / "scripts-stub.py"


@pytest.fixture
def compile_template():
    """Byte-compile a packaged template, the way importing or installing one does."""
    stub = shipped_root() / TEMPLATE
    if not stub.exists():  # pragma: no cover - shipped tree changed
        pytest.skip(f"{TEMPLATE.as_posix()} is no longer shipped")
    cache = stub.parent / "__pycache__"

    def compile_it() -> Path:
        compileall.compile_file(str(stub), quiet=2)
        assert cache.exists(), "nothing was compiled; the test would prove nothing"
        return cache

    yield compile_it
    if cache.exists():
        for path in cache.glob("*"):
            path.unlink()
        cache.rmdir()


def test_check_is_satisfiable_when_the_package_carries_bytecode(tmp_path: Path, compile_template) -> None:
    """The headline defect: --check demanded a file install-skills could not produce."""
    install_skills(tmp_path)
    assert differences(tmp_path) == [], "clean install already drifted"

    compile_template()
    assert differences(tmp_path) == []


def test_install_does_not_copy_bytecode_into_the_adopter_repo(tmp_path: Path, compile_template) -> None:
    compile_template()
    install_skills(tmp_path)
    leaked = [
        p.relative_to(tmp_path).as_posix()
        for p in tmp_path.rglob("*")
        if "__pycache__" in p.parts or p.suffix in {".pyc", ".pyo"}
    ]
    assert leaked == [], f"bytecode copied into the adopter's repo: {leaked}"

"""Bytecode inside the shipped skill tree is not skill content.

`policy-init` ships template `.py` files. Byte-compiling one writes `__pycache__/` beside
it, and inside a pip-installed package that lands in the shipped tree -- which is why this
only ever appeared in CI, where the framework is installed rather than run from a checkout.

Two consequences, both wrong:

  `install-skills --check` reported `missing: .../__pycache__/scripts-stub.cpython-312.pyc`,
  demanding the adopter hold a `.pyc` built on another machine for another Python version.
  `install-skills` could not produce it, so the check could not be satisfied by the command
  it tells you to run.

  `install_skills` copied the directory in, so an adopter committed another machine's
  bytecode into `.agents/skills/`.

Found by adding `install-skills --check` to the catalog's CI, on the first run.
"""

from __future__ import annotations

import compileall
from pathlib import Path

import pytest

from chock.scaffold.skills import differences, install_skills, shipped_root

TEMPLATE = Path("policy-init") / "assets" / "templates" / "scripts-stub.py"


@pytest.fixture
def compile_template():
    """Byte-compile a packaged template, the way importing or installing one does.

    Handed to the test as a callable rather than run up front, because *when* the bytecode
    appears is the whole bug: the adopter installs from a clean tree, and the `.pyc` shows
    up afterwards on the machine running the check.
    """
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
    """The headline defect: --check demanded a file install-skills could not produce.

    Install from a clean tree first -- an adopter's committed skills predate whatever
    bytecode later appears in site-packages. Compiling before installing would put the
    `.pyc` on both sides and prove nothing.
    """
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

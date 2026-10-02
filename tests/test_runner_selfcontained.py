"""The vendored runner must remain stdlib-only and chock-free."""

from __future__ import annotations

from pathlib import Path

from chock.gate.assemble import runner_source


def test_runner_has_no_nonstdlib_or_chock_imports() -> None:
    source = runner_source()

    assert "import yaml" not in source, "gate.py must not import yaml"
    assert "from chock" not in source, "gate.py must not import from chock"
    assert "from ." not in source, "gate.py is one file: no relative import may survive assembly"


def test_vendored_gate_py_matches_source() -> None:
    vendored = Path(__file__).resolve().parents[1] / ".chock" / "bin" / "gate.py"
    assert runner_source().encode("utf-8") == vendored.read_bytes(), (
        "vendored .chock/bin/gate.py must be byte-identical to the assembled chock.gate.runner package"
    )

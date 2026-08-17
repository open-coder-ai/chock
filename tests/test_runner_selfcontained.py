"""The vendored runner must remain stdlib-only and chock-free."""

from __future__ import annotations

from pathlib import Path


def test_runner_has_no_nonstdlib_or_chock_imports() -> None:
    runner = Path(__file__).resolve().parents[1] / "src" / "chock" / "gate" / "runner.py"
    source = runner.read_text(encoding="utf-8")

    assert "import yaml" not in source, "runner.py must not import yaml"
    assert "from chock" not in source, "runner.py must not import from chock"


def test_vendored_gate_py_matches_source() -> None:
    runner = Path(__file__).resolve().parents[1] / "src" / "chock" / "gate" / "runner.py"
    vendored = Path(__file__).resolve().parents[1] / ".chock" / "bin" / "gate.py"
    assert runner.read_bytes() == vendored.read_bytes(), (
        "vendored .chock/bin/gate.py must be byte-identical to src/chock/gate/runner.py"
    )

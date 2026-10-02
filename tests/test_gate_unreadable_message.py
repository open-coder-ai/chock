"""A gate that cannot be read still refuses, and its message names no path."""

from __future__ import annotations

from pathlib import Path

import pytest

from chock.gate.runner import run

EXIT_CANNOT_JUDGE = 2


def _unreadable(tmp_path: Path, kind: str) -> Path:
    gate = tmp_path / "secret-dir" / "gate.json"
    if kind == "directory":
        gate.mkdir(parents=True)
    else:
        gate.parent.mkdir()
        gate.write_text("{not json", encoding="utf-8")
    return gate


@pytest.mark.parametrize("kind", ["directory", "malformed"])
def test_unreadable_gate_refuses_without_naming_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    gate = _unreadable(tmp_path, kind)

    code = run(gate, "commit", None, tmp_path)

    err = capsys.readouterr().err
    assert code == EXIT_CANNOT_JUDGE
    assert "cannot read the compiled gate this hook names" in err
    assert "secret-dir" not in err
    assert str(tmp_path) not in err

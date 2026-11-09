"""tools/render_runtime.py renders exactly the runtime goldens' file set, so semgrep on CI misses no target."""

from __future__ import annotations

from pathlib import Path

import pytest
import render_runtime

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "runtime_goldens"


def test_the_render_writes_every_file_the_goldens_freeze(tmp_path: Path) -> None:
    written = {p.name for p in render_runtime.write(tmp_path / "out")}
    assert written == {p.name for p in GOLDEN.glob("*.py")}


def test_the_render_refuses_a_directory_that_already_holds_files(tmp_path: Path) -> None:
    (tmp_path / "stale.py").write_text("", encoding="utf-8")
    with pytest.raises(render_runtime.NotEmptyError):
        render_runtime.write(tmp_path)

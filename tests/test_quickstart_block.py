"""tools/quickstart_block.py: extracts the README's first ```bash Quick start block."""

from __future__ import annotations

from pathlib import Path

import pytest
import quickstart_block

ROOT = Path(__file__).resolve().parents[1]


def test_extracts_real_readme_block() -> None:
    block = quickstart_block.extract_first_bash_block((ROOT / "README.md").read_text())
    assert "chock init ." in block
    assert "chock add scan-secrets" in block
    assert "chock sync --repo ." in block


def test_stops_at_next_heading_without_a_bash_fence() -> None:
    text = "## Quick start\n\nsome prose, no fence here\n\n## Next section\n\n```bash\nfoo\n```\n"
    with pytest.raises(quickstart_block.NoBashBlockError):
        quickstart_block.extract_first_bash_block(text)


def test_missing_heading_raises() -> None:
    with pytest.raises(quickstart_block.NoQuickStartHeadingError):
        quickstart_block.extract_first_bash_block("# Title\n\nno quick start here\n")


def test_ignores_a_non_bash_fence_before_the_bash_one() -> None:
    text = "## Quick start\n\n```text\nnot this\n```\n\n```bash\necho real\n```\n"
    assert quickstart_block.extract_first_bash_block(text) == "echo real\n"


def test_main_prints_block_to_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("## Quick start\n\n```bash\necho hi\n```\n")
    assert quickstart_block.main([str(readme)]) == 0
    assert capsys.readouterr().out == "echo hi\n"

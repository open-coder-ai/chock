"""tools/changelog.py: fragment validation and Unreleased assembly; the repo's own fragments pass."""

from __future__ import annotations

import subprocess
from pathlib import Path

import changelog
import pytest

ROOT = Path(__file__).resolve().parents[1]
LOG = "# Log\n\n## Unreleased\n\n- old entry\n\n## 1.0.0\n\n- shipped\n"


def make_repo(tmp_path: Path, frags: dict[str, str], log: str = LOG) -> Path:
    (tmp_path / "CHANGELOG.md").write_text(log, encoding="utf-8")
    (tmp_path / "changelog.d").mkdir()
    for name, body in frags.items():
        (tmp_path / "changelog.d" / name).write_text(body, encoding="utf-8")
    return tmp_path


def test_repo_fragments_are_valid() -> None:
    assert changelog.check(ROOT) == []


def test_cli_check_passes_on_repo() -> None:
    assert changelog.main(["--check"]) == 0


@pytest.mark.parametrize(
    ("body", "needle"),
    [
        ("", "empty"),
        ("  \n\n", "empty"),
        ("prose, not a bullet\n", "must start"),
        ("- ok\n## Heading\n", "headings"),
        ("- ok\nstray line\n", "neither a bullet"),
    ],
)
def test_invalid_fragments_are_reported(tmp_path: Path, body: str, needle: str) -> None:
    root = make_repo(tmp_path, {"bad.md": body})
    assert any(needle in problem for problem in changelog.check(root))


def test_valid_multiline_fragment_passes(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {"a.md": "- **x.** one\n  continued\n\n- second\n"})
    assert changelog.check(root) == []


def test_readme_is_not_a_fragment(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {"README.md": "explains things\n", "a.md": "- a\n"})
    assert [p.name for p in changelog.fragments(root)] == ["a.md"]


def test_assemble_orders_existing_then_fragments_by_filename(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {"b.md": "- bee\n", "a.md": "- ay\n"})
    out = changelog.assemble(root)
    assert out.index("old entry") < out.index("ay") < out.index("bee") < out.index("## 1.0.0")
    assert out.startswith("# Log\n\n## Unreleased\n")
    assert out.endswith("- shipped\n")


def test_assemble_without_existing_entries(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {"a.md": "- ay\n"}, log="## Unreleased\n\n## 1.0.0\n- shipped\n")
    assert changelog.assemble(root).startswith("## Unreleased\n\n- ay\n")


def test_assemble_requires_unreleased_heading(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {}, log="# Log\n\n## 1.0.0\n")
    with pytest.raises(ValueError, match="Unreleased"):
        changelog.assemble(root)


def test_unreleased_as_last_section(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {"a.md": "- ay\n"}, log="## Unreleased\n\n- old\n")
    assert changelog.assemble(root) == "## Unreleased\n\n- old\n- ay\n"


def test_cli_assemble_prints_and_write_rewrites(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_repo(tmp_path, {"a.md": "- ay\n"})
    assert changelog.main(["--assemble", "--root", str(root)]) == 0
    printed = capsys.readouterr().out
    assert "- ay" in printed
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == LOG
    assert changelog.main(["--assemble", "--write", "--root", str(root)]) == 0
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == printed


def test_cli_check_fails_and_names_the_fragment(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_repo(tmp_path, {"bad.md": ""})
    assert changelog.main(["--check", "--root", str(root)]) == 1
    assert "bad.md: empty" in capsys.readouterr().err


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
    )


def test_base_check_flags_a_branch_that_edits_changelog(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {"a.md": "- a\n"})
    git(root, "init", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-m", "base")
    git(root, "checkout", "-b", "feature")
    assert changelog.check(root, "main") == []
    (root / "CHANGELOG.md").write_text(LOG + "- sneaky\n", encoding="utf-8")
    git(root, "commit", "-am", "edit")
    assert any("edited against main" in problem for problem in changelog.check(root, "main"))

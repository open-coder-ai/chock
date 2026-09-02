"""tools/check_literal_duplication.py: the check itself, and that src/ passes it."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import check_literal_duplication as literal_dup
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_src_has_no_undeclared_repeated_literals() -> None:
    violations = literal_dup.find_violations(ROOT / "src")
    assert not violations, f"repeated literals need a constant or an allowlist entry: {sorted(violations)}"


def test_allowlist_entries_all_carry_a_reason() -> None:
    allowlist = literal_dup.load_allowlist()
    for literal, reason in allowlist.items():
        assert isinstance(reason, str) and reason.strip(), literal


def test_allowlist_rejects_empty_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = tmp_path / "allowlist.json"
    bad.write_text(json.dumps({"some literal": "   "}), encoding="utf-8")
    monkeypatch.setattr(literal_dup, "ALLOWLIST_PATH", bad)
    with pytest.raises(ValueError, match="no reason"):
        literal_dup.load_allowlist()


def test_docstrings_are_not_flagged(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text(
        textwrap.dedent(
            '''
            """This is a plenty-long module docstring, repeated below."""

            class C:
                """This is a plenty-long module docstring, repeated below."""

                def m(self):
                    """This is a plenty-long module docstring, repeated below."""
            '''
        ),
        encoding="utf-8",
    )
    assert literal_dup.scan(tmp_path) == {}


def test_repeated_non_docstring_literal_is_found(tmp_path: Path) -> None:
    literal = "x" * 25
    (tmp_path / "a.py").write_text(f'A = "{literal}"\n', encoding="utf-8")
    (tmp_path / "b.py").write_text(f'B = "{literal}"\n', encoding="utf-8")
    (tmp_path / "c.py").write_text(f'C = "{literal}"\n', encoding="utf-8")
    occurrences = literal_dup.scan(tmp_path)
    assert len(occurrences[literal]) == 3


def test_short_literals_are_not_flagged(tmp_path: Path) -> None:
    short = "x" * (literal_dup.MIN_LITERAL_LEN - 1)
    for name in "abc":
        (tmp_path / f"{name}.py").write_text(f'V = "{short}"\n', encoding="utf-8")
    assert literal_dup.scan(tmp_path) == {}


def test_data_templates_tests_dirs_are_excluded(tmp_path: Path) -> None:
    literal = "y" * 25
    for sub in ("data", "templates", "tests"):
        d = tmp_path / sub
        d.mkdir()
        (d / "m.py").write_text(f'V = "{literal}"\n', encoding="utf-8")
    (tmp_path / "one_more.py").write_text(f'V = "{literal}"\n', encoding="utf-8")
    occurrences = literal_dup.scan(tmp_path)
    # Only the top-level file counts -- the three excluded dirs don't contribute.
    assert occurrences[literal] == [tmp_path / "one_more.py"]


def test_allowlisted_literal_is_not_a_violation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    literal = "z" * 25
    for name in "abc":
        (tmp_path / f"{name}.py").write_text(f'V = "{literal}"\n', encoding="utf-8")
    allowlist_path = tmp_path / "allowlist.json"
    allowlist_path.write_text(json.dumps({literal: "deliberately shared across a, b, c"}), encoding="utf-8")
    monkeypatch.setattr(literal_dup, "ALLOWLIST_PATH", allowlist_path)
    assert literal_dup.find_violations(tmp_path) == {}


def test_cli_reports_violations_via_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    literal = "w" * 25
    for name in "abc":
        (tmp_path / f"{name}.py").write_text(f'V = "{literal}"\n', encoding="utf-8")
    monkeypatch.setattr(literal_dup, "ALLOWLIST_PATH", tmp_path / "does-not-exist.json")
    assert literal_dup.main([str(tmp_path)]) == 1
    assert literal in capsys.readouterr().err

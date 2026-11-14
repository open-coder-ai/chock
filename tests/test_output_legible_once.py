"""IR-F75: each defaulted manifest field is said once per command, with its path. IR-F76: no character a console cannot show."""

from __future__ import annotations

import io
import re
import subprocess
import sys
from pathlib import Path

import pytest

from chock.cli import main
from chock.eval.model import Case, CaseResult, PolicyResult
from chock.eval.report import render_text
from chock.output import ellipsis, legible, new_command, warn
from chock.pipe import PipeTolerantWriter

DEFAULTED = re.compile(r"defaulted (\S+) to ")
SKILL = ".agents/skills/demo"


def _repo_with_bare_skill(root: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    skill = root / SKILL
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo\ndescription: A demo skill.\n---\n# Demo\n", encoding="utf-8")
    return root


def _cp1252() -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252")


def test_check_says_each_defaulted_field_once_and_names_the_skill(tmp_path: Path, capsys, monkeypatch) -> None:
    repo = _repo_with_bare_skill(tmp_path)
    monkeypatch.chdir(repo)

    main(["check", "--repo", "."])

    captured = capsys.readouterr()
    lines = (captured.err + captured.out).splitlines()
    defaulted = [line for line in lines if DEFAULTED.search(line)]
    fields = [DEFAULTED.search(line).group(1) for line in defaulted]
    assert "version" in fields
    assert len(fields) == len(set(fields)), defaulted
    assert all(SKILL in line for line in defaulted), defaulted


def test_a_second_command_in_the_same_process_says_them_again(tmp_path: Path, capsys, monkeypatch) -> None:
    repo = _repo_with_bare_skill(tmp_path)
    monkeypatch.chdir(repo)
    counts = []
    for _ in range(2):
        main(["check", "--repo", "."])
        captured = capsys.readouterr()
        counts.append(sum("defaulted version" in line for line in (captured.out + captured.err).splitlines()))
    assert counts == [1, 1]


def _long_result() -> PolicyResult:
    case = Case(id="c1", category="block", prompt="p", expect="block", policy_id="demo")
    return PolicyResult("demo", "deterministic", [CaseResult(case, "fail", detail="x" * 200)])


def test_the_eval_table_on_a_cp1252_stream_has_no_ellipsis_character(monkeypatch) -> None:
    stream = _cp1252()
    monkeypatch.setattr(sys, "stdout", stream)

    PipeTolerantWriter(stream).write(render_text([_long_result()]))
    stream.flush()

    text = stream.buffer.getvalue().decode("cp1252")
    assert "\u2026" not in text
    assert "x" * 60 + "..." in text


def test_a_utf8_stream_keeps_the_ellipsis(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="utf-8"))
    assert ellipsis() == "\u2026"
    assert "\u2026" in render_text([_long_result()])


@pytest.mark.parametrize(
    ("text", "shown"),
    [("a \u2014 b", "a -- b"), ("x \u2192 y", "x -> y"), ("\u00a75", "s.5"), ("caf\u00e9 \u20ac", "caf\u00e9 \u20ac")],
)
def test_legible_turns_chock_symbols_into_ascii_on_a_legacy_code_page(text: str, shown: str) -> None:
    assert legible(text, _cp1252()) == shown


def test_warn_on_a_cp1252_stderr_never_raises_and_prints_ascii(monkeypatch) -> None:
    stream = _cp1252()
    monkeypatch.setattr(sys, "stderr", stream)
    new_command()
    warn("lock \u2014 run the regen \u2026")
    stream.flush()
    assert stream.buffer.getvalue().decode("ascii") == "[WARN] lock -- run the regen ...\n"

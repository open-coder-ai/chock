"""A script gate that prints keyed findings is judged on the findings its change introduces.

The runner runs the script on the change, and again on the baseline text; a finding whose key
the baseline does not account for is new. Only new findings decide, in the change-run's exit code.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from findings_support import judge_write, make_gate, repo_with

OLD = "x = BAD\n"
SANITIZED = "sanitize(a)\nquery(a)\n"


def test_an_old_violation_untouched_is_allowed(tmp_path: Path, toy_runs: Callable[[], list[str]]) -> None:
    repo = repo_with(tmp_path, **{"app.py": OLD})
    assert judge_write(make_gate(repo), repo, OLD + "y = 1\n") == 0
    assert toy_runs() == ["change", "baseline"]


def test_a_new_violation_blocks_and_names_only_it(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = repo_with(tmp_path, **{"app.py": OLD})
    assert judge_write(make_gate(repo), repo, OLD + "y = BAD two\n") == 1
    err = capsys.readouterr().err
    assert "app.py:2: bad y = BAD two" in err
    assert "x = BAD" not in err
    assert "RAW-STDERR" not in err


def test_a_deleted_sanitizer_that_makes_a_finding_appear_blocks(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, **{"app.py": SANITIZED})
    assert judge_write(make_gate(repo), repo, "query(a)\n") == 1


def test_a_line_shift_is_not_a_new_finding(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, **{"app.py": OLD})
    assert judge_write(make_gate(repo), repo, "# one\n# two\n# three\n" + OLD) == 0


def test_a_duplicated_violation_blocks(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = repo_with(tmp_path, **{"app.py": OLD})
    assert judge_write(make_gate(repo), repo, OLD + OLD) == 1
    assert "app.py:2:" in capsys.readouterr().err


def test_a_finding_is_matched_per_path(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, **{"a.py": OLD})
    assert judge_write(make_gate(repo), repo, OLD, path="b.py") == 1


def test_a_new_file_is_judged_whole_and_needs_no_baseline_run(
    tmp_path: Path, toy_runs: Callable[[], list[str]]
) -> None:
    repo = repo_with(tmp_path, **{"app.py": "x = 1\n"})
    assert judge_write(make_gate(repo), repo, OLD, path="fresh.py") == 1
    assert toy_runs() == ["change"]


def test_a_clean_change_needs_no_baseline_run(tmp_path: Path, toy_runs: Callable[[], list[str]]) -> None:
    repo = repo_with(tmp_path, **{"app.py": OLD})
    assert judge_write(make_gate(repo), repo, "x = 1\n") == 0
    assert toy_runs() == ["change"]


def test_a_baseline_that_crashes_blocks_when_the_change_has_findings(tmp_path: Path) -> None:
    old = "x = BAD BASECRASH\n"
    repo = repo_with(tmp_path, **{"app.py": old})
    assert judge_write(make_gate(repo), repo, old + "y = 1\n") == 1


def test_a_baseline_that_outruns_the_shared_budget_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from chock.gate import runner

    repo = repo_with(tmp_path, **{"app.py": OLD})
    gate = make_gate(repo)
    monkeypatch.setattr(runner.script, "_SCRIPT_TIMEOUT_SECONDS", 2)
    monkeypatch.setenv("TOY_SLEEP", "1.2")
    assert judge_write(gate, repo, OLD + "y = 1\n") == 1


@pytest.mark.parametrize(("code", "exit_code"), [("3", 3), ("4", 4)])
def test_ask_and_warn_are_the_change_runs_verdict_for_new_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: str, exit_code: int
) -> None:
    monkeypatch.setenv("TOY_EXIT", code)
    repo = repo_with(tmp_path, **{"app.py": OLD})
    gate = make_gate(repo)
    assert judge_write(gate, repo, OLD + "y = BAD two\n") == exit_code
    assert judge_write(gate, repo, OLD + "y = 1\n") == 0


def test_a_finding_marked_new_always_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOY_NEW", "1")
    repo = repo_with(tmp_path, **{"app.py": OLD})
    assert judge_write(make_gate(repo), repo, OLD + "y = 1\n") == 1


def test_a_script_without_a_document_keeps_the_exit_code_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, toy_runs: Callable[[], list[str]], capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("TOY_MODE", "plain")
    repo = repo_with(tmp_path, **{"app.py": OLD})
    gate = make_gate(repo)
    assert judge_write(gate, repo, OLD + "y = 1\n") == 1
    assert "plain: bad in app.py" in capsys.readouterr().err
    assert judge_write(gate, repo, "x = 1\n") == 0
    assert toy_runs() == ["change", "change"]


def test_a_document_with_a_malformed_finding_is_not_a_document(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = repo_with(tmp_path, **{"app.py": OLD})
    gate = make_gate(repo)
    script = repo / "toy.py"
    script.write_text(
        'import sys\nprint(\'{"findings": [{"key": "k"}]}\')\nprint("raw words", file=sys.stderr)\nsys.exit(1)\n'
    )
    assert judge_write(gate, repo, OLD) == 1
    assert "raw words" in capsys.readouterr().err


def test_a_document_then_an_unknown_exit_is_undecided_not_a_pass(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """A script that prints an empty document and then crashes or exits oddly has decided nothing."""
    repo = repo_with(tmp_path, **{"app.py": OLD})
    gate = make_gate(repo)
    (repo / "toy.py").write_text("import sys\nprint('{\"findings\": []}')\nsys.exit(7)\n")
    assert judge_write(gate, repo, OLD) == 1
    assert "exited 7" in capsys.readouterr().err


def test_a_committed_change_is_judged_against_head(tmp_path: Path) -> None:
    from conftest import stage

    from chock.gate.runner import run

    repo = repo_with(tmp_path, **{"app.py": OLD})
    gate = make_gate(repo)
    stage(repo, "app.py", OLD + "y = 1\n")
    assert run(gate, "pre-commit", None, repo) == 0
    stage(repo, "app.py", OLD + "y = BAD two\n")
    assert run(gate, "pre-commit", None, repo) == 1

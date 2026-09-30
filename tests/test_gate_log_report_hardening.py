"""The gate-log report stays correct and inert whatever a log line holds (review follow-ups to #203)."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_gate_log_report import SQL, TRAVERSAL, by, event, week, write_log

from chock import lifecycle
from chock.gatelog import main


def test_by_rule_counts_each_rules_own_new_findings() -> None:
    record = event(1, "block", rules={SQL: 2, TRAVERSAL: 1}, new_findings=3, matches=["a.py:1: x", "b.py:2: y"])

    groups = by([record], "rule")

    assert (groups[SQL]["new_findings"], groups[TRAVERSAL]["new_findings"]) == (2, 1)
    assert by([record], "policy")["java-security"]["new_findings"] == 3


def test_top_files_break_ties_by_path() -> None:
    records = [event(1, "block", matches=[f"{name}.py: x" for name in ("c", "a", "d", "b")])]

    assert [f["path"] for f in by(records, "policy")["java-security"]["files"]] == ["a.py", "b.py", "c.py"]


def test_markdown_cells_cannot_open_a_link_or_double_a_backslash(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    write_log(tmp_path, [event(1, "block", agent="[ok](https://example.test) x\\|y")])

    assert main(["--repo", str(tmp_path), "--format", "md", "--by", "agent"]) == 0

    row = capsys.readouterr().out.splitlines()[4]
    assert row.startswith("| \\[ok\\](https://example.test) x\\\\\\|y |")


def test_text_output_drops_terminal_control_characters(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    write_log(tmp_path, [event(1, "block", agent="evil\x1b]0;title\x07agent"), event(2, "block", agent="plain")])

    assert main(["--repo", str(tmp_path), "--by", "agent"]) == 0

    out = capsys.readouterr().out
    assert "\x1b" not in out and "\x07" not in out
    assert "evil?]0;title?agent" in out and "plain" in out


@pytest.mark.parametrize("days", ["0", "-3"])
def test_since_must_be_a_positive_number_of_days(tmp_path: Path, days: str) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["--repo", str(tmp_path), "--since", days])

    assert stopped.value.code == 2
    assert main(["--repo", str(tmp_path), "--since", "1"]) == 0


@pytest.mark.parametrize("flag", [["--json"], ["--format", "md"]])
def test_chock_status_prints_machine_output_only_for_the_log_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture, flag: list[str]
) -> None:
    write_log(tmp_path, week())

    assert lifecycle.status_main(["--repo", str(tmp_path), "--only", "policies,log", *flag]) == 2
    assert capsys.readouterr().out == ""
    assert lifecycle.status_main(["--repo", str(tmp_path), "--only", "log", *flag]) == 0

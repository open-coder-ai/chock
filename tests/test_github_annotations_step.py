"""The annotations of one CI step share GitHub's per-step limit, and nothing they print can hurt the gate."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from test_github_annotations import _commands, _finding, _repo

from chock.gate import runner
from chock.gate.runner import ci_inert, judge

STEP = {"GITHUB_RUN_ID": "7", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_JOB": "gate", "GITHUB_ACTION": "__run_2"}


@pytest.fixture
def step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """One GitHub Actions step: a runner temp directory and a step summary file."""
    temp = tmp_path / "runner-temp"
    temp.mkdir()
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_TEMP", str(temp))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    for name, value in STEP.items():
        monkeypatch.setenv(name, value)
    return summary


def _gates(tmp_path: Path, count: int, per_gate: int) -> list[tuple[Path, Path]]:
    gates = []
    for n in range(count):
        root = tmp_path / f"repo{n}"
        root.mkdir()
        gates.append(_repo(root, [_finding(i) for i in range(1, per_gate + 1)]))
    return gates


def test_every_gate_in_a_step_shares_ten_errors(tmp_path: Path, step: Path, capsys: pytest.CaptureFixture) -> None:
    for repo, gate in _gates(tmp_path, 3, 12):
        assert judge(gate, "ci", None, repo, base="HEAD~1") == (1, "block")
    assert len(_commands(capsys.readouterr().out)) == 10
    text = step.read_text(encoding="utf-8")
    assert text.count("#### Not annotated") == 3
    listed = [line for line in text.splitlines() if line.startswith("- src/")]
    assert len(listed) == 3 * 12 - 10, "every finding not annotated is in the summary"


def test_a_new_step_gets_a_new_budget(tmp_path: Path, step: Path, monkeypatch, capsys) -> None:
    (repo, gate), (repo2, gate2) = _gates(tmp_path, 2, 12)
    judge(gate, "ci", None, repo, base="HEAD~1")
    monkeypatch.setenv("GITHUB_ACTION", "__run_3")
    judge(gate2, "ci", None, repo2, base="HEAD~1")
    assert len(_commands(capsys.readouterr().out)) == 20


def test_a_corrupt_budget_prints_no_annotation_and_keeps_the_verdict(tmp_path: Path, step: Path, capsys) -> None:
    ((repo, gate),) = _gates(tmp_path, 1, 2)
    key = "-".join(STEP[name] for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "GITHUB_ACTION"))
    (Path(str(step.parent / "runner-temp")) / f"chock-annotations-{key}.json").write_text("{", encoding="utf-8")
    assert judge(gate, "ci", None, repo, base="HEAD~1") == (1, "block")
    assert _commands(capsys.readouterr().out) == []
    assert "#### Not annotated (2" in step.read_text(encoding="utf-8")


def test_an_unencodable_message_neither_crashes_nor_hides_the_refusal(tmp_path: Path, step: Path, capsys) -> None:
    repo, gate = _repo(tmp_path, [_finding(1, message="bad \ud800 here")])
    assert judge(gate, "ci", None, repo, base="HEAD~1") == (1, "block")
    out, err = capsys.readouterr()
    assert len(_commands(out)) == 1 and "src/f01.py" in err


def test_an_annotation_failure_is_reported_and_changes_nothing(tmp_path, step: Path, monkeypatch, capsys) -> None:
    repo, gate = _repo(tmp_path, [_finding(1)])

    def broken(*_args: object) -> None:
        raise RuntimeError

    monkeypatch.setattr(runner.report, "_annotate", broken)
    assert judge(gate, "ci", None, repo, base="HEAD~1") == (1, "block")
    err = capsys.readouterr().err
    assert "GitHub annotations skipped: RuntimeError" in err and "src/f01.py" in err


def test_the_refusal_on_stderr_cannot_start_a_workflow_command(tmp_path: Path, step: Path, capsys) -> None:
    hostile = _finding(1, path="::stop-commands::tok", message="x\n  ::add-mask::secret\r::set-env name=A::b")
    repo, gate = _repo(tmp_path, [hostile])
    assert judge(gate, "ci", None, repo, base="HEAD~1") == (1, "block")
    err = capsys.readouterr().err
    assert not [line for line in err.splitlines() if line.strip().startswith("::")]
    assert "> ::stop-commands::tok" in err


def test_a_warned_finding_stays_in_the_log_as_inert_text(tmp_path: Path, step: Path, capsys) -> None:
    repo, gate = _repo(tmp_path, [_finding(1, message="m\n::add-mask::x")], rollout="observe")
    assert judge(gate, "ci", None, repo, base="HEAD~1") == (0, "warn")
    out, err = capsys.readouterr()
    assert _commands(out)[0].startswith("::warning ")
    assert "gate: warning:" in err
    assert not [line for line in err.splitlines() if line.strip().startswith("::")]


def test_ordinary_text_is_left_alone() -> None:
    assert ci_inert("src/a.py:3: bad\n  - b.py:4: worse") == "src/a.py:3: bad\n  - b.py:4: worse"


def test_the_aggregate_warning_escapes_its_title() -> None:
    assert runner._annotation("a,b:c", "r") == "::warning title=chock a%2Cb%3Ac::r"


def test_the_summary_renders_no_link_image_or_mention() -> None:
    cell = runner._cell("[click](https://x.test) ![i](https://t.test) @org/team")
    assert "[click]" not in cell and "![" not in cell and " @org" not in cell
    assert cell.startswith("\\[click\\]")


def test_text_a_stream_cannot_encode_is_replaced() -> None:
    stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    assert runner._encodable("é \ud800", stream) == "? ?"


def test_off_a_runner_each_gate_caps_alone(tmp_path: Path, step: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("RUNNER_TEMP")
    for repo, gate in _gates(tmp_path, 2, 12):
        judge(gate, "ci", None, repo, base="HEAD~1")
    assert len(_commands(capsys.readouterr().out)) == 20

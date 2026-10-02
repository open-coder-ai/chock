"""GitHub Actions annotations from the ci gate: one workflow command per new finding, output only."""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest
from conftest import init_repo

from chock.gate.runner import judge

POLICY = "demo-policy"
EMIT = textwrap.dedent(
    """\
    import json, sys
    payload = json.load(sys.stdin)
    findings = json.load(open(payload["repo_root"] + "/emit.json"))
    print(json.dumps({"findings": findings}))
    sys.exit(1 if findings else 0)
    """
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _finding(n: int = 1, **over: object) -> dict:
    return {"key": f"k{n}", "path": f"src/f{n:02}.py", "line": n, "message": f"bad {n}", "new": True, **over}


def _repo(tmp_path: Path, findings: list[dict], *, rollout: str | None = None) -> tuple[Path, Path]:
    repo = init_repo(tmp_path)
    (repo / "emit.py").write_text(EMIT, encoding="utf-8")
    (repo / "emit.json").write_text(json.dumps(findings), encoding="utf-8")
    (repo / "base.txt").write_text("ok\n", encoding="utf-8")
    if rollout:
        (repo / ".chock").mkdir()
        (repo / ".chock" / "config.yaml").write_text(f"rollout: {rollout}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-qm", "change")
    gate = repo / ".chock" / "compiled" / POLICY / "git-hook" / "gate.json"
    gate.parent.mkdir(parents=True, exist_ok=True)
    spec = {"kind": "script", "on": ["commit"], "action": "block", "message": "m", "params": {"script": "emit.py"}}
    gate.write_text(json.dumps(spec), encoding="utf-8")
    return repo, gate


def _ci(gate: Path, repo: Path, monkeypatch: pytest.MonkeyPatch, *, actions: str | None, summary: Path | None = None):
    for name in ("GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY", "RUNNER_TEMP"):
        monkeypatch.delenv(name, raising=False)
    if actions is not None:
        monkeypatch.setenv("GITHUB_ACTIONS", actions)
    if summary is not None:
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    return judge(gate, "ci", None, repo, base="HEAD~1")


def _commands(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("::")]


def test_an_error_annotation_carries_escaped_properties(tmp_path, monkeypatch, capsys) -> None:
    item = _finding(3, path="src/a,b:c.py", rule="r:1", message="100% bad\r\nnext")
    repo, gate = _repo(tmp_path, [item])
    assert _ci(gate, repo, monkeypatch, actions="true") == (1, "block")
    assert _commands(capsys.readouterr().out) == [
        f"::error file=src/a%2Cb%3Ac.py,line=3,title=chock {POLICY}%3A r%3A1::100%25 bad%0D%0Anext"
    ]


def test_a_finding_without_a_rule_titles_the_policy_alone(tmp_path, monkeypatch, capsys) -> None:
    repo, gate = _repo(tmp_path, [_finding(2)])
    _ci(gate, repo, monkeypatch, actions="true")
    assert _commands(capsys.readouterr().out) == [f"::error file=src/f02.py,line=2,title=chock {POLICY}::bad 2"]


def test_paths_are_repo_relative_with_forward_slashes(tmp_path, monkeypatch, capsys) -> None:
    repo, gate = _repo(tmp_path, [_finding(1, path="./win\\dir\\a.py"), _finding(2, path=str(tmp_path / "abs.py"))])
    _ci(gate, repo, monkeypatch, actions="true")
    lines = _commands(capsys.readouterr().out)
    assert lines[0].startswith("::error file=win/dir/a.py,line=1,")
    assert lines[1].startswith("::error file=abs.py,line=2,")


def test_a_path_outside_the_repo_is_annotated_without_a_file(tmp_path, monkeypatch, capsys) -> None:
    repo, gate = _repo(tmp_path, [_finding(1, path="../escape.py"), _finding(2, path="/etc/passwd")])
    _ci(gate, repo, monkeypatch, actions="true")
    assert all(line.startswith(f"::error title=chock {POLICY}::") for line in _commands(capsys.readouterr().out))


def test_at_most_ten_annotations_and_the_rest_in_the_summary(tmp_path, monkeypatch, capsys) -> None:
    repo, gate = _repo(tmp_path, [_finding(n) for n in range(13, 0, -1)])
    summary = tmp_path / "summary.md"
    assert _ci(gate, repo, monkeypatch, actions="true", summary=summary) == (1, "block")
    lines = _commands(capsys.readouterr().out)
    assert len(lines) == 10
    assert lines[0].startswith("::error file=src/f01.py,line=1,")
    assert lines[-1].startswith("::error file=src/f10.py,line=10,")
    text = summary.read_text(encoding="utf-8")
    assert f"| {POLICY} | 13 | 0 | block |" in text
    assert "Not annotated (3: GitHub shows 10 errors and 10 warnings per step)" in text
    assert [f"- src/f{n}.py:{n}: bad {n}" in text for n in (11, 12, 13)] == [True] * 3
    assert "src/f10.py" not in text


def test_no_overflow_section_under_the_cap(tmp_path, monkeypatch) -> None:
    repo, gate = _repo(tmp_path, [_finding(1)])
    summary = tmp_path / "summary.md"
    _ci(gate, repo, monkeypatch, actions="true", summary=summary)
    text = summary.read_text(encoding="utf-8")
    assert "| policy | new findings | baseline | verdict |" in text
    assert "Not annotated" not in text


def test_the_summary_is_appended_not_replaced(tmp_path, monkeypatch) -> None:
    repo, gate = _repo(tmp_path, [_finding(1)])
    summary = tmp_path / "summary.md"
    summary.write_text("earlier step\n", encoding="utf-8")
    _ci(gate, repo, monkeypatch, actions="true", summary=summary)
    assert summary.read_text(encoding="utf-8").startswith("earlier step\n")


def test_observe_mode_annotates_as_warnings(tmp_path, monkeypatch, capsys) -> None:
    repo, gate = _repo(tmp_path, [_finding(1)], rollout="observe")
    summary = tmp_path / "summary.md"
    assert _ci(gate, repo, monkeypatch, actions="true", summary=summary) == (0, "warn")
    out = capsys.readouterr().out
    assert _commands(out) == [f"::warning file=src/f01.py,line=1,title=chock {POLICY}::bad 1"]
    assert f"| {POLICY} | 1 | 0 | warn |" in summary.read_text(encoding="utf-8")


def test_a_warn_script_annotates_warnings_only(tmp_path, monkeypatch, capsys) -> None:
    repo, gate = _repo(tmp_path, [_finding(1)], rollout="observe")
    assert _ci(gate, repo, monkeypatch, actions="true")[0] == 0
    assert not [line for line in _commands(capsys.readouterr().out) if line.startswith("::error")]


@pytest.mark.parametrize("actions", [None, "false", "TRUE", ""])
def test_outside_github_actions_nothing_is_annotated_and_no_summary_is_written(
    tmp_path, monkeypatch, capsys, actions
) -> None:
    repo, gate = _repo(tmp_path, [_finding(1)])
    summary = tmp_path / "summary.md"
    assert _ci(gate, repo, monkeypatch, actions=actions, summary=summary) == (1, "block")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert not summary.exists()


def test_outside_github_actions_observe_output_keeps_the_plain_warning(tmp_path, monkeypatch, capsys) -> None:
    repo, gate = _repo(tmp_path, [_finding(1)], rollout="observe")
    _ci(gate, repo, monkeypatch, actions=None)
    out = capsys.readouterr().out
    assert out.startswith(f"::warning title=chock {POLICY}::")
    assert "file=" not in out


@pytest.mark.parametrize("rollout", [None, "ask", "observe"])
def test_verdict_and_exit_code_are_the_same_with_and_without_annotations(tmp_path, monkeypatch, rollout) -> None:
    repo, gate = _repo(tmp_path, [_finding(n) for n in range(1, 15)], rollout=rollout)
    summary = tmp_path / "summary.md"
    plain = _ci(gate, repo, monkeypatch, actions=None)
    annotated = _ci(gate, repo, monkeypatch, actions="true", summary=summary)
    assert annotated == plain
    assert summary.exists()


def test_an_unwritable_summary_does_not_change_the_verdict(tmp_path, monkeypatch, capsys) -> None:
    repo, gate = _repo(tmp_path, [_finding(1)])
    assert _ci(gate, repo, monkeypatch, actions="true", summary=tmp_path / "missing" / "s.md") == (1, "block")
    assert "cannot write the step summary" in capsys.readouterr().err


def test_untrusted_text_cannot_inject_a_second_workflow_command(tmp_path, monkeypatch, capsys) -> None:
    evil = _finding(
        1,
        path="a,b:c\n::add-mask::z.py",
        rule="r\n::stop-commands::tok",
        message="oops\n::set-env name=X::y\r::error::again",
    )
    repo, gate = _repo(tmp_path, [evil])
    summary = tmp_path / "summary.md"
    assert _ci(gate, repo, monkeypatch, actions="true", summary=summary) == (1, "block")
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("::error ")
    assert "\r" not in lines[0]
    assert "oops%0A::set-env name=X::y%0D::error::again" in lines[0]
    assert not [line for line in lines if line.startswith(("::set-env", "::add-mask", "::stop-commands"))]


def test_untrusted_text_cannot_break_out_of_the_summary(tmp_path, monkeypatch) -> None:
    many = [_finding(n, message="x\n::set-env name=X::y | `z` <b>") for n in range(1, 13)]
    repo, gate = _repo(tmp_path, many)
    summary = tmp_path / "summary.md"
    _ci(gate, repo, monkeypatch, actions="true", summary=summary)
    lines = summary.read_text(encoding="utf-8").splitlines()
    assert not [line for line in lines if line.startswith("::")]
    assert not any("<b>" in line or "`" in line for line in lines)

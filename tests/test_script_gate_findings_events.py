"""Where a script gate's baseline comes from at each event, and that eval replay and packages get it too."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from conftest import init_repo
from findings_support import NAME, TOY, commit, gate_spec, judge_write, make_gate, repo_with

from chock.eval.execute import run_case
from chock.eval.model import Case
from chock.gate import runner
from chock.gate.runner import run

OLD = "x = BAD\n"
EVENTS = ["pre-tool-use", "stop"]


def test_pre_tool_use_judges_against_the_disk_and_stop_against_head(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, **{"app.py": OLD})
    gate = make_gate(repo)
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    assert judge_write(gate, repo, OLD, event="pre-tool-use") == 1
    assert judge_write(gate, repo, OLD, event="stop") == 0


def test_pre_tool_use_allows_what_the_disk_already_holds(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, **{"app.py": "x = 1\n"})
    gate = make_gate(repo)
    (repo / "app.py").write_text(OLD, encoding="utf-8")
    assert judge_write(gate, repo, OLD + "y = 1\n", event="pre-tool-use") == 0
    assert judge_write(gate, repo, OLD + "y = 1\n", event="stop") == 1


def test_a_ci_range_is_judged_against_its_base(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, **{"app.py": OLD})
    gate = make_gate(repo)
    base = commit(repo, **{"keep.py": "k = 1\n"})
    commit(repo, **{"app.py": OLD + "y = 1\n"})
    assert run(gate, "ci", None, repo, base=base) == 0
    commit(repo, **{"app.py": OLD + "y = BAD two\n"})
    assert run(gate, "ci", None, repo, base=base) == 1


def test_an_outside_repo_path_is_judged_against_the_disk_before_the_write(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, **{"app.py": "x = 1\n"})
    gate = make_gate(repo)
    outside = tmp_path / "elsewhere" / "notes.py"
    outside.parent.mkdir()
    outside.write_text(OLD, encoding="utf-8")
    assert run(gate, "pre-tool-use", None, repo, writes={str(outside): OLD + "y = 1\n"}) == 0
    assert run(gate, "pre-tool-use", None, repo, writes={str(outside): OLD + "y = BAD two\n"}) == 1


def test_an_outside_repo_path_with_no_file_is_judged_whole(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, **{"app.py": "x = 1\n"})
    gate = make_gate(repo)
    assert run(gate, "pre-tool-use", None, repo, writes={str(tmp_path / "absent.py"): OLD}) == 1


# --- a repo_root below the git top-level --------------------------------------------------------------


def _nested(tmp_path: Path, text: str) -> Path:
    top = repo_with(tmp_path)
    commit(top, **{"sub/app.py": text})
    return top / "sub"


def test_head_is_read_from_a_repo_root_below_the_git_top_level(tmp_path: Path) -> None:
    sub = _nested(tmp_path, OLD)
    gate = make_gate(sub)
    assert judge_write(gate, sub, OLD + "y = 1\n", event="stop") == 0
    assert judge_write(gate, sub, OLD + "y = BAD two\n", event="stop") == 1


def test_a_waiver_in_head_is_honoured_from_a_repo_root_below_the_git_top_level(tmp_path: Path) -> None:
    """content_regex read HEAD from the top-level, so a nested root never saw the waiver already committed."""
    waived = "x = eval(a)  # chock: allow eval\n"
    sub = _nested(tmp_path, waived)
    params = {"content_pattern": r"\beval\(", "allowlist_pragma": r"chock:\s*allow\s+eval"}
    spec = {"kind": "content_regex", "on": ["tool_use"], "action": "block", "message": "m", "params": params}
    (sub / "gate.json").write_text(json.dumps(spec), encoding="utf-8")
    assert run(sub / "gate.json", "stop", None, sub, writes={"app.py": waived + "z = 1\n"}) == 0


def test_the_agent_runner_names_paths_from_the_directory_it_works_in(tmp_path: Path) -> None:
    sub = _nested(tmp_path, OLD)
    make_gate(sub)
    proc = subprocess.run(
        [sys.executable, str(Path(runner.__file__)), "run", "--gate", str(sub / "gate.json"), "--event", "stop"],
        input=json.dumps({"writes": {"app.py": OLD + "y = 1\n"}}),
        cwd=sub,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_a_missing_git_or_repo_means_no_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    gate = make_gate(plain)
    assert judge_write(gate, plain, OLD, event="stop") == 1
    monkeypatch.setattr(runner, "_GIT", str(tmp_path / "no-git"))
    assert judge_write(gate, plain, OLD, event="stop") == 1


# --- a packaged plugin's script sits beside its gate ---------------------------------------------------


def test_a_packaged_script_gets_its_baseline_run_too(tmp_path: Path, toy_runs) -> None:
    package = tmp_path / "plugin" / "scripts"
    (package / "implementations").mkdir(parents=True)
    (package / "implementations" / NAME).write_text(TOY, encoding="utf-8")
    spec = {**gate_spec(f"implementations/{NAME}", ("tool_use",)), "script_base": "gate"}
    (package / "gate.json").write_text(json.dumps(spec), encoding="utf-8")
    (tmp_path / "project").mkdir()
    project = init_repo(tmp_path / "project")
    commit(project, **{"app.py": OLD})
    assert run(package / "gate.json", "stop", None, project, writes={"app.py": OLD + "y = 1\n"}) == 0
    assert run(package / "gate.json", "stop", None, project, writes={"app.py": OLD + "y = BAD two\n"}) == 1
    assert toy_runs() == ["change", "baseline"] * 2


# --- an eval case can say both things ----------------------------------------------------------------


def _policy(root: Path) -> Path:
    policy = root / ".agents" / "policies" / "toy-findings"
    (policy / "implementations").mkdir(parents=True)
    manifest = {
        "id": "toy-findings",
        "name": "Toy",
        "version": "0.0.1",
        "description": "d",
        "artifact": "hook",
        "enforcement": "block",
        "hook": {"gate": gate_spec(NAME)},
        "provenance": {"author": "t"},
        "lifecycle": {"status": "draft"},
    }
    manifest["hook"]["gate"]["params"] = {"script": NAME}
    (policy / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (policy / "implementations" / NAME).write_text(TOY, encoding="utf-8")
    return policy


def _case(execute: dict) -> Case:
    return Case(id="t", category="trigger", prompt="p", expect="e", policy_id="toy-findings", execute=execute)


@pytest.mark.parametrize(
    ("head", "files", "event", "expect"),
    [
        (OLD, OLD + "y = 1\n", "commit", "allow"),
        ("sanitize(a)\nquery(a)\n", "query(a)\n", "commit", "block"),
        (OLD, OLD + "y = 1\n", "tool_use", "allow"),
        ("sanitize(a)\nquery(a)\n", "query(a)\n", "tool_use", "block"),
    ],
)
def test_an_eval_case_expresses_old_violations_and_deleted_sanitizers(
    tmp_path: Path, head: str, files: str, event: str, expect: str
) -> None:
    root = tmp_path / "adopter"
    root.mkdir()
    policy = _policy(root)
    execute = {"head_files": {"app.py": head}, "files": {"app.py": files}, "event": event, "expect": expect}
    result = run_case(_case(execute), policy, root, guards=[])
    assert result.outcome == "pass", result.detail

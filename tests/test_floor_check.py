"""`chock check --floor`: the base's gates bind, waivers count only from the base, ask refuses, nothing of the head runs."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from floor_support import (
    FLOOR_TOKEN,
    MARKER_SCRIPT,
    PROBE,
    TEST_FILE,
    TEST_PRAGMA,
    base_repo,
    commit,
    gate,
    git,
    run_floor,
    write,
)

from chock.lifecycle import check_main

SRC = Path(__file__).resolve().parents[1] / "src"

NO_OP = {"kind": "content_regex", "on": ["commit"], "action": "warn", "params": {"content_pattern": "(?!)"}}


def test_a_head_rewrite_of_the_gate_does_not_stop_the_base_gate(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    gate(repo, "test-integrity", NO_OP)
    (repo / "tests/test_core.py").unlink()
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert "FAIL test-integrity [base] (block)" in out
    assert "tests/test_core.py: test file deleted" in out


def test_a_waiver_the_pull_request_adds_is_not_honoured(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    write(repo, "tests/test_core.py", f"def test_a():\n    # {TEST_PRAGMA}\n    assert 1 + 1 == 2\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert "assertions removed across tests" in out


def test_a_base_waiver_on_a_line_the_pull_request_removes_is_not_honoured(tmp_path, capsys) -> None:
    """V4: a waiver counts only on a line present and unchanged in both base and head."""
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    write(repo, "tests/test_core.py", TEST_FILE.replace("== 4\n", f"== 4  # {TEST_PRAGMA}\n"))
    commit(repo, "base waiver")
    git(repo, "checkout", "-q", "-B", "pr")
    write(repo, "tests/test_core.py", "def test_a():\n    assert 1 + 1 == 2\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "assertions removed across tests" in out


def test_ask_counts_as_a_refusal(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    gate(repo, "floor-token", {**FLOOR_TOKEN, "action": "ask"})
    commit(repo, "ask")
    git(repo, "checkout", "-q", "-B", "pr")
    write(repo, "src/app.py", "VALUE = 'FLOOR-TOKEN-1'\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert "FAIL floor-token [base] (ask)" in out


def test_a_secret_added_then_removed_is_found_by_the_history_pass(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    write(repo, "src/app.py", "VALUE = 'FLOOR-TOKEN-7'\n")
    first = commit(repo, "add")
    write(repo, "src/app.py", "VALUE = 1\n")
    commit(repo, "remove")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert f"FAIL floor-token [history] (block): {first[:12]} src/app.py:1 (content-pattern)" in out


def test_a_line_already_at_the_base_is_not_the_pull_requests(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    write(repo, "src/app.py", "VALUE = 'FLOOR-TOKEN-3'\n")
    commit(repo, "before adoption")
    git(repo, "checkout", "-q", "-B", "pr")
    write(repo, "src/app.py", "VALUE = 'FLOOR-TOKEN-3'\nOTHER = 2\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def test_a_script_gate_gets_deleted_paths_and_no_environment(tmp_path, capsys, monkeypatch) -> None:
    repo = base_repo(tmp_path)
    (repo / "src/app.py").unlink()
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1
    assert "probe: deleted src/app.py" in out
    write(repo, "src/app.py", "VALUE = 1\n")
    commit(repo, "restore")
    monkeypatch.setenv("FLOOR_PROBE_SECRET", "1")
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def test_no_head_file_is_executed(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    write(repo, PROBE["params"]["script"], MARKER_SCRIPT)
    gate(repo, "new-probe", {**PROBE, "params": {"script": "tools/new_probe.py"}}, surfaces=("ci-gate",))
    write(repo, "tools/new_probe.py", MARKER_SCRIPT)
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert not (repo / "MARKER").exists()
    assert "new-probe" not in out.replace(".chock/compiled/new-probe/", "")
    assert code == 1, out
    assert f"\n  {PROBE['params']['script']}\n" in out


def test_the_head_is_read_as_objects_from_a_base_checkout(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    (repo / ".cursor/hooks.json").unlink()
    commit(repo, "pr")
    git(repo, "checkout", "-q", "main")
    code, out = run_floor(repo, capsys, "--head", "pr")
    assert code == 1
    assert "FAIL floor/control-plane-changed (refuse): 1 path(s)" in out
    assert "\n  .cursor/hooks.json\n" in out


def test_an_unresolvable_base_is_undecided(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    code = check_main(["--repo", str(repo), "--floor", "--base", "no-such-ref"])
    assert code == 2
    assert "does not resolve" in capsys.readouterr().err


def test_a_branch_gate_without_the_branch_is_undecided(tmp_path, capsys) -> None:
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    gate(
        repo,
        "protect-main",
        {"kind": "forbidden_ref", "on": ["commit"], "action": "block", "params": {"refs": ["main"]}},
    )
    commit(repo, "ref gate")
    git(repo, "checkout", "-q", "-B", "pr")
    write(repo, "src/other.py", "X = 1\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 2
    assert "needs --head-ref" in out
    code, out = run_floor(repo, capsys, "--head-ref", "pr")
    assert code == 0, out
    code, out = run_floor(repo, capsys, "--head-ref", "main")
    assert code == 1


@pytest.mark.parametrize(
    "argv",
    [
        ["--floor"],
        ["--floor", "--base", "main", "--only", "verify"],
        ["--head", "x"],
        ["--floor", "--base", "m", "--format", "sarif"],
    ],
)
def test_the_floor_runs_alone_and_needs_a_base(tmp_path, argv) -> None:
    with pytest.raises(SystemExit) as exc:
        check_main(["--repo", str(tmp_path), *argv])
    assert exc.value.code == 2


def test_no_coverage_tier_is_credited_for_the_floor() -> None:
    """A floor is the adopter's required-check setting, which chock cannot see: nothing grades it."""
    from chock.evidence import CLAIMS_PATH

    assert "floor" not in CLAIMS_PATH.read_text(encoding="utf-8").lower()
    from chock.compile import surfaces

    assert not [name for name in vars(surfaces) if "floor" in name.lower()]


def test_head_not_descendant_of_base_is_undecided(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    write(repo, "src/app.py", "VALUE = 9\n")
    commit(repo, "main moves on")
    git(repo, "checkout", "-q", "pr")
    code, out = run_floor(repo, capsys, "--head", "pr")
    assert code == 2, out
    assert "is not an ancestor of head" in out


def _cli(repo: Path, *args: str) -> int:
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(SRC), "HOME": str(repo.parent)}
    code = "import sys; from chock.lifecycle import check_main; sys.exit(check_main(sys.argv[1:]))"
    proc = subprocess.run(
        [sys.executable, "-c", code, "--repo", str(repo), *args], capture_output=True, text=True, env=env, check=False
    )
    return proc.returncode


def test_ref_arguments(tmp_path):
    repo = base_repo(tmp_path)
    write(repo, "src/config.txt", "key = FLOOR-TOKEN-4242\n")
    commit(repo, "pr")
    assert _cli(repo, "--floor", "--base", "main", "--head", "pr") == 1
    assert _cli(repo, "--floor", "--base", "no-such-ref", "--head", "pr") == 2
    assert _cli(repo, "--floor", "--base=--all", "--head", "pr") == 2
    assert _cli(repo, "--floor", "--base=--since=2000-01-01", "--head", "pr") == 2
    assert _cli(repo, "--floor", "--base", "main", f"--head=--output={tmp_path / 'x'}") == 2
    assert _cli(repo, "--floor", "--base", "pr", "--head", "pr") == 0

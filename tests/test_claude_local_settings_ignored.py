"""`.claude/settings.local.json` stays out of git (and an existing .dockerignore) for repos targeting Claude Code."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import init_repo

from chock import output
from chock.scaffold.gitrules import CLAUDE_LOCAL_SETTINGS, ensure_git_rules

RULE = CLAUDE_LOCAL_SETTINGS


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_a_new_repo_targeting_claude_gets_the_rule(tmp_path: Path) -> None:
    ensure_git_rules(tmp_path, ["claude", "copilot"])
    assert _lines(tmp_path / ".gitignore").count(RULE) == 1


def test_a_repo_not_targeting_claude_gets_nothing(tmp_path: Path) -> None:
    (tmp_path / ".dockerignore").write_text("node_modules\n", encoding="utf-8")
    ensure_git_rules(tmp_path, ["copilot", "gemini"])
    ensure_git_rules(tmp_path)
    assert RULE not in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert (tmp_path / ".dockerignore").read_text(encoding="utf-8") == "node_modules\n"


@pytest.mark.parametrize("equivalent", [RULE, f"{RULE}/", f"  {RULE}  "])
def test_an_equivalent_rule_means_nothing_is_written(tmp_path: Path, equivalent: str) -> None:
    ensure_git_rules(tmp_path)
    before = (tmp_path / ".gitignore").read_text(encoding="utf-8") + f"{equivalent}\n"
    (tmp_path / ".gitignore").write_text(before, encoding="utf-8")
    ensure_git_rules(tmp_path, ["claude"])
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == before


def test_a_tracked_copy_gets_the_rule_and_one_notice_and_stays_tracked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = init_repo(tmp_path)
    (repo / ".claude").mkdir()
    (repo / RULE).write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", RULE], cwd=repo, check=True)
    output.new_command()
    ensure_git_rules(repo, ["claude"])
    ensure_git_rules(repo, ["claude"])
    err = capsys.readouterr().err
    assert err.count(f"git rm --cached {RULE}") == 1
    assert "git commit" in err
    assert RULE in _lines(repo / ".gitignore")
    tracked = subprocess.run(["git", "ls-files", RULE], cwd=repo, capture_output=True, text=True, check=True)
    assert tracked.stdout.strip() == RULE
    assert (repo / RULE).read_text(encoding="utf-8") == "{}\n"


def test_an_untracked_copy_prints_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = init_repo(tmp_path)
    output.new_command()
    ensure_git_rules(repo, ["claude"])
    assert "git rm --cached" not in capsys.readouterr().err


def test_an_existing_dockerignore_gets_the_line_and_none_is_created(tmp_path: Path) -> None:
    ensure_git_rules(tmp_path, ["claude"])
    assert not (tmp_path / ".dockerignore").exists()
    (tmp_path / ".dockerignore").write_text(".git", encoding="utf-8")
    ensure_git_rules(tmp_path, ["claude"])
    assert _lines(tmp_path / ".dockerignore") == [".git", _lines(tmp_path / ".dockerignore")[1], RULE]
    assert _lines(tmp_path / ".dockerignore")[1].startswith("# chock:")


def test_a_second_run_is_byte_identical(tmp_path: Path) -> None:
    (tmp_path / ".dockerignore").write_text("a\n", encoding="utf-8")
    ensure_git_rules(tmp_path, ["claude"])
    first = ((tmp_path / ".gitignore").read_bytes(), (tmp_path / ".dockerignore").read_bytes())
    ensure_git_rules(tmp_path, ["claude"])
    assert ((tmp_path / ".gitignore").read_bytes(), (tmp_path / ".dockerignore").read_bytes()) == first


def test_a_crlf_gitignore_stays_crlf(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_bytes(b"dist/\r\nnode_modules/\r\n")
    ensure_git_rules(tmp_path, ["claude"])
    data = (tmp_path / ".gitignore").read_bytes()
    assert data.startswith(b"dist/\r\nnode_modules/\r\n")
    assert data.count(b"\n") == data.count(b"\r\n")
    assert data.count(RULE.encode()) == 1
    ensure_git_rules(tmp_path, ["claude"])
    assert (tmp_path / ".gitignore").read_bytes() == data

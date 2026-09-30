"""A global `bin/` ignore must not take `.chock/bin/` out of an adopter's repository.

Found by chock-catalog's agent test kit on Windows: the `bin/` in the Visual Studio, .NET and Java
gitignore templates matched `.chock/bin/`, `git add -A` never tracked it, the first `git clean -x`
deleted it, and Claude Code reported `SessionStart:startup hook error ... can't open file
'.chock/bin/claude_code.py'` -- after which no hook could start the gate. chock now tracks its
runtime explicitly, and `chock check` says so when a hook target is missing or ignored.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import baseline_policy, init_repo

from chock.scaffold.gitrules import GATE_LOG_IGNORE, RUNTIME_BYTECODE_IGNORE, TRACKED_RUNTIME, ensure_git_rules
from chock.scaffold.recompile import recompile
from chock.validation.checks_hook_targets import check_dangling_hook_targets
from chock.validation.report import Report

RUNTIME = ".chock/bin/claude_code.py"


@pytest.fixture
def global_bin_ignore(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A machine whose global excludes file ignores `bin/`, as the common templates do."""
    home = tmp_path_factory.mktemp("machine")
    excludes = home / "global-gitignore"
    excludes.write_text("[Bb]in/\nobj/\n", encoding="utf-8")
    config = home / "global-gitconfig"
    config.write_text(f"[core]\n\texcludesFile = {excludes.as_posix()}\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    return excludes


def _wired(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path)
    # A command guard (the runtime alone) and a write gate (the runtime and a compiled gate).
    for policy in ("block-destructive-commands", "pin-github-actions"):
        shutil.copytree(baseline_policy(policy), repo / ".agents" / "policies" / policy)
    recompile(repo, ["claude"], skip_hooks=False)
    assert (repo / RUNTIME).is_file()
    return repo


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)


def _without_runtime_rules(repo: Path) -> None:
    """An adopter's .gitignore from before chock tracked its runtime explicitly."""
    gitignore = repo / ".gitignore"
    kept = [line for line in gitignore.read_text(encoding="utf-8").splitlines() if line not in TRACKED_RUNTIME]
    gitignore.write_text("\n".join(kept) + "\n", encoding="utf-8")


@pytest.mark.usefixtures("global_bin_ignore")
def test_the_runtime_is_tracked_despite_a_global_bin_ignore(tmp_path: Path) -> None:
    repo = _wired(tmp_path)
    assert _git(repo, "check-ignore", "-q", RUNTIME).returncode == 1, "the runtime would be ignored"
    _git(repo, "add", "-A")
    tracked = _git(repo, "ls-files", ".chock/bin", ".chock/compiled").stdout.splitlines()
    assert RUNTIME in tracked
    assert any(path.endswith("gate.json") for path in tracked)
    assert _git(repo, "check-ignore", "-q", ".chock/log/gate-events.jsonl").returncode == 0


@pytest.mark.usefixtures("global_bin_ignore")
def test_an_ignored_runtime_is_an_error_that_names_the_rule(tmp_path: Path) -> None:
    repo = _wired(tmp_path)
    _without_runtime_rules(repo)
    report = Report()
    check_dangling_hook_targets(repo, report)
    messages = [f.message for f in report.errors if f.check == "dangling_hook_target"]
    assert messages, "an ignored runtime passed the check"
    assert all("is ignored by git" in m and "global-gitignore" in m for m in messages)
    assert any(RUNTIME in m for m in messages)


@pytest.mark.usefixtures("global_bin_ignore")
def test_sync_restores_the_rules_for_an_adopter_who_initialised_earlier(tmp_path: Path) -> None:
    repo = _wired(tmp_path)
    _without_runtime_rules(repo)
    recompile(repo, ["claude"], skip_hooks=False)
    report = Report()
    check_dangling_hook_targets(repo, report)
    assert report.errors == []


def test_a_missing_compiled_gate_is_a_dangling_target(tmp_path: Path) -> None:
    repo = _wired(tmp_path)
    shutil.rmtree(repo / ".chock" / "compiled")
    report = Report()
    check_dangling_hook_targets(repo, report)
    messages = [f.message for f in report.errors]
    assert messages
    assert all(".chock/compiled/" in m and "does not exist" in m for m in messages)


def test_the_rules_are_written_once_and_an_adopters_own_are_kept(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("target/\n.chock/log\n!.chock/bin\n", encoding="utf-8")
    ensure_git_rules(tmp_path)
    ensure_git_rules(tmp_path)
    lines = gitignore.read_text(encoding="utf-8").splitlines()
    assert lines[:3] == ["target/", ".chock/log", "!.chock/bin"]
    assert GATE_LOG_IGNORE not in lines
    assert lines.count("!.chock/compiled/") == 1
    assert "!.chock/bin/" not in lines


def test_a_repository_with_no_gitignore_gets_both_rules(tmp_path: Path) -> None:
    ensure_git_rules(tmp_path)
    lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert {GATE_LOG_IGNORE, *TRACKED_RUNTIME} <= set(lines)


def test_a_path_a_negation_re_includes_is_not_reported_as_ignored(tmp_path: Path) -> None:
    """`git check-ignore -v` names a matching `!` rule and exits 0 even though the path is kept."""
    repo = _wired(tmp_path)
    assert "!.chock/bin/**" in (repo / ".gitignore").read_text(encoding="utf-8").splitlines()
    report = Report()
    check_dangling_hook_targets(repo, report)
    assert report.errors == []


def test_runtime_bytecode_stays_out_though_the_runtime_is_tracked(tmp_path: Path) -> None:
    """Running a hook writes `__pycache__` under `.chock/bin/`; `!.chock/bin/**` must not re-include it."""
    repo = _wired(tmp_path)
    cache = repo / ".chock" / "bin" / "__pycache__"
    cache.mkdir(exist_ok=True)
    (cache / "claude_code.cpython-312.pyc").write_bytes(b"\x00")
    (repo / ".chock" / "compiled" / "stray.pyc").write_bytes(b"\x00")
    assert _git(repo, "check-ignore", "-q", ".chock/bin/__pycache__/claude_code.cpython-312.pyc").returncode == 0
    assert _git(repo, "check-ignore", "-q", ".chock/compiled/stray.pyc").returncode == 0
    assert _git(repo, "check-ignore", "-q", RUNTIME).returncode == 1, "the runtime itself must stay tracked"


def test_an_existing_gitignore_gains_the_runtime_bytecode_rules_once(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("node_modules/\n!.chock/bin/**\n", encoding="utf-8")
    ensure_git_rules(tmp_path)
    ensure_git_rules(tmp_path)
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    for rule in RUNTIME_BYTECODE_IGNORE:
        assert text.count(rule) == 1
    assert text.index(".chock/bin/**/__pycache__/") > text.index("!.chock/bin/**")

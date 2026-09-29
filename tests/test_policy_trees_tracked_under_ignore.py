"""A `build/` ignore must not take a policy's `build/` sub-package out of an adopter's repository.

Found in live testing: the java-security policy ships `rules/build/`, Java and Gradle repos (and many
global gitignores) ignore `build/`, so a fresh clone had no such folder and the gate crashed with
`ImportError: cannot import name 'build'` -- after which the hook refused every edit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import init_repo

from chock.scaffold.gitrules import ensure_git_rules

POLICY = ".agents/policies/java-security/implementations/chock_security/rules"
SOURCE = f"{POLICY}/build/gradle.py"
BYTECODE = f"{POLICY}/build/__pycache__/gradle.cpython-312.pyc"
STRAY_PYC = f"{POLICY}/style/loose.pyc"
OWN_OUTPUT = "build/output.class"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)


def _write(repo: Path, rel: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 1\n", encoding="utf-8")


def _populate(repo: Path) -> None:
    for rel in (SOURCE, f"{POLICY}/style/naming.py", BYTECODE, STRAY_PYC, OWN_OUTPUT):
        _write(repo, rel)


def _tracked_after_add(repo: Path) -> list[str]:
    _git(repo, "add", "-A")
    return _git(repo, "ls-files").stdout.splitlines()


def _assert_policy_kept_output_ignored(tracked: list[str]) -> None:
    assert SOURCE in tracked, "the policy's build/ sub-package was ignored"
    assert f"{POLICY}/style/naming.py" in tracked
    assert BYTECODE not in tracked
    assert STRAY_PYC not in tracked
    assert OWN_OUTPUT not in tracked, "the adopter's own build output was un-ignored"


def test_a_global_build_ignore_does_not_drop_a_policy_build_package(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path_factory.mktemp("machine")
    excludes = home / "global-gitignore"
    excludes.write_text("build/\n", encoding="utf-8")
    config = home / "global-gitconfig"
    config.write_text(f"[core]\n\texcludesFile = {excludes.as_posix()}\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    repo = init_repo(tmp_path_factory.mktemp("repo"))
    ensure_git_rules(repo)
    _populate(repo)
    _assert_policy_kept_output_ignored(_tracked_after_add(repo))


def test_a_repository_build_ignore_does_not_drop_a_policy_build_package(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / ".gitignore").write_text("build/\nout/\ntarget/\n", encoding="utf-8")
    ensure_git_rules(repo)
    _populate(repo)
    _assert_policy_kept_output_ignored(_tracked_after_add(repo))


def test_the_bytecode_ignores_come_after_the_policy_negations(tmp_path: Path) -> None:
    ensure_git_rules(tmp_path)
    lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    last_negation = max(i for i, line in enumerate(lines) if line.startswith("!.agents/policies/"))
    assert lines.index(".agents/policies/**/__pycache__/") > last_negation
    assert lines.index(".agents/policies/**/*.pyc") > last_negation


def test_the_policy_rules_are_written_once(tmp_path: Path) -> None:
    ensure_git_rules(tmp_path)
    ensure_git_rules(tmp_path)
    lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines.count("!.agents/policies/**") == 1
    assert lines.count(".agents/policies/**/*.pyc") == 1

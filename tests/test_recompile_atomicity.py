"""recompile builds into a staging tree and swaps on success.

Before this, recompile deleted .chock/compiled and zeroed coverage.json up front, then
compiled. A failure partway through -- one malformed manifest among many -- left every
policy's gate deleted, coverage empty, and chock.lock pointing at artifacts that no longer
existed: one typo disabling enforcement repo-wide. A failed recompile must leave the repo
exactly as it was.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from conftest import baseline_policy

from chock.scaffold import recompile as recompile_mod
from chock.scaffold.recompile import recompile


def _repo_with_one_policy(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".agents" / "policies").mkdir(parents=True)
    (repo / ".chock").mkdir()
    (repo / ".chock" / "config.yaml").write_text("chock:\n  supported_agents: [claude]\n", encoding="utf-8")
    shutil.copytree(baseline_policy("protect-main-branch"), repo / ".agents" / "policies" / "protect-main-branch")
    return repo


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_failed_recompile_leaves_the_live_tree_intact(tmp_path: Path, monkeypatch) -> None:
    repo = _repo_with_one_policy(tmp_path)
    # a first, successful recompile establishes the live compiled tree + coverage
    recompile(repo, ["claude"], skip_hooks=True)
    compiled = repo / ".chock" / "compiled"
    coverage = repo / ".chock" / "coverage.json"
    assert compiled.is_dir() and any(compiled.iterdir())

    before_compiled = _snapshot(compiled)
    before_coverage = coverage.read_bytes()

    # now a build that blows up partway through
    def boom(*_a, **_k):
        raise RuntimeError("bad manifest partway through the loop")

    monkeypatch.setattr(recompile_mod, "_compile_all", boom)
    with pytest.raises(RuntimeError):
        recompile(repo, ["claude"], skip_hooks=True)

    # the live tree is byte-for-byte what it was: no gate deleted, no coverage zeroed
    assert _snapshot(compiled) == before_compiled, "a failed recompile deleted live compiled artifacts"
    assert coverage.read_bytes() == before_coverage, "a failed recompile zeroed coverage.json"


def test_successful_recompile_still_replaces_stale_output(tmp_path: Path) -> None:
    # atomicity must not stop a good recompile from clearing artifacts of a removed policy.
    repo = _repo_with_one_policy(tmp_path)
    recompile(repo, ["claude"], skip_hooks=True)
    stale = repo / ".chock" / "compiled" / "ghost-policy" / "git-hook"
    stale.mkdir(parents=True)
    (stale / "gate.json").write_text("{}", encoding="utf-8")

    recompile(repo, ["claude"], skip_hooks=True)
    assert not (repo / ".chock" / "compiled" / "ghost-policy").exists(), "stale output survived the swap"
    assert (repo / ".chock" / "compiled" / "protect-main-branch").is_dir()
    assert (repo / ".chock" / "bin" / "gate.py").exists(), "the vendored runner must land in the live tree"

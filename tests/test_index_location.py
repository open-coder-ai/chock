"""The policy index sits under .chock/bin: guarded by protect-agent-config, tolerated by lock, verify and compiled_drift."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from conftest import baseline_policy

from chock.hooks.multi_wiring import INDEX_DIR
from chock.scaffold.recompile import compiled_differences, recompile

AGENTS = ["claude"]


@pytest.fixture
def wired_repo(tmp_path: Path) -> Path:
    """A repo with a shell guard compiled and its hooks installed into Claude's config."""
    policy = tmp_path / ".agents" / "policies" / "block-destructive-commands"
    policy.parent.mkdir(parents=True)
    shutil.copytree(
        baseline_policy("block-destructive-commands"), policy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    recompile(tmp_path, AGENTS)
    return tmp_path


def test_the_index_folder_is_tolerated_by_lock_verify_and_compiled_drift(wired_repo: Path) -> None:
    """The index sits under a path protect-agent-config guards, and nothing counts it as stale or unlocked."""
    from chock.lock import build_lock, verify_lock, write_lock
    from chock.validation.checks_drift import check_compiled_drift
    from chock.validation.report import Report

    assert any((wired_repo / INDEX_DIR).glob("claude_code-PreToolUse-*.json"))
    (wired_repo / ".chock" / "config.yaml").write_text("chock:\n  supported_agents: [claude]\n", encoding="utf-8")
    write_lock(build_lock(wired_repo), wired_repo)

    assert verify_lock(wired_repo) == (True, [])
    assert not compiled_differences(wired_repo, AGENTS)
    report = Report()
    check_compiled_drift(wired_repo, report)
    assert report.is_clean()


def test_the_index_folder_is_a_path_the_agent_config_guard_protects() -> None:
    """INDEX_DIR matches the forbidden_path_regex of protect-agent-config, so an agent cannot rewrite an index."""
    import re

    manifest = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / ".agents/policies/protect-agent-config/manifest.yaml").read_text(
            encoding="utf-8"
        )
    )
    patterns = re.findall(r"forbidden_path_regex: '([^']+)'", yaml.safe_dump(manifest, width=10**6)) or re.findall(
        r"forbidden_path_regex: '([^']+)'",
        (Path(__file__).resolve().parents[1] / ".agents/policies/protect-agent-config/manifest.yaml").read_text(
            encoding="utf-8"
        ),
    )
    assert patterns
    assert all(re.search(p, f"{INDEX_DIR.as_posix()}/claude_code-PreToolUse-0.json") for p in patterns)

"""#151: a hook config naming a `.chock/bin/` runtime `sync` already deleted is a silent
client-side failure -- every tool call runs a hook whose command fails before the gate runs,
and neither `chock sync --check` nor `chock check` used to say so.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from conftest import baseline_policy, init_repo

from chock.scaffold.recompile import recompile
from chock.validation.checks_hook_targets import check_dangling_hook_targets
from chock.validation.report import Report
from chock.vendors import CHOCK_AGENT


def _repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path)
    shutil.copytree(
        baseline_policy("block-destructive-commands"), repo / ".agents" / "policies" / "block-destructive-commands"
    )
    return repo


def test_a_hand_planted_dangling_entry_fails(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    recompile(repo, ["cursor"], skip_hooks=False)
    cursor_hooks = repo / ".cursor" / "hooks.json"
    assert cursor_hooks.exists()

    (repo / ".chock" / "bin" / "cursor.py").unlink()

    report = Report()
    check_dangling_hook_targets(repo, report)
    assert [f.check for f in report.errors] == ["dangling_hook_target"]
    assert ".chock/bin/cursor.py" in report.errors[0].message
    assert "chock sync" in report.errors[0].message


def test_a_clean_tree_is_silent(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    recompile(repo, ["cursor", "claude"], skip_hooks=False)

    report = Report()
    check_dangling_hook_targets(repo, report)
    assert report.errors == []


def test_a_repo_with_no_hook_configs_is_silent(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    report = Report()
    check_dangling_hook_targets(repo, report)
    assert report.errors == []


def test_the_fixed_sync_leaves_nothing_for_it_to_find(tmp_path: Path) -> None:
    """#151's exact repro: every vendor wired, then narrowed to one -- `sync` must clean up
    after itself so this check has nothing left to report."""
    repo = _repo(tmp_path)
    recompile(repo, sorted(CHOCK_AGENT), skip_hooks=False)
    recompile(repo, ["claude"], skip_hooks=False)

    report = Report()
    check_dangling_hook_targets(repo, report)
    assert report.errors == []

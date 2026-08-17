"""`install-hooks` and `recompile` must agree about coverage.json.

They did not. `install-hooks` wrote `enforced` into the file for every guard whose
PreToolUse fragment it had just installed; `recompile` derived the same field from the
manifests and wrote `advisory` back. Two commands, one file, opposite answers:

  install hooks     -> guard reads `enforced`
  recompile --check -> "compiled artifacts are out of date" (exit 1)
  recompile         -> guard silently reads `advisory` again

So adopting the framework the documented way left the repo failing its own freshness check,
and the obvious fix for that failure quietly dropped the enforcement claim. Found by running
the catalog as an adopter, not by any test here.

The fix is that coverage is derived, always. `.claude/settings.json` is a committed file, so
"is this fragment installed" is a question about repo contents and CI reaches the same
answer from the same checkout.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from chock.hooks.pretooluse_install import install_pretooluse_hooks, installed_pretooluse_policy_ids
from chock.scaffold.recompile import compiled_differences, recompile

AGENTS = ["claude"]

# The PreToolUse emitter matches policies to guard scripts by id (GUARD_SCRIPTS), so this
# has to be one of the ids it knows or no fragment is written and there is nothing to
# install. Using a real id keeps the fixture honest about what the emitter actually does.
GUARD = {
    "id": "block-no-verify",
    "name": "block-no-verify",
    "version": "0.0.1",
    "description": "test guard",
    "artifact": "hook",
    "enforcement": "block",
    "effects": ["read_only"],
    "approval": {"required": False},
    "hook": {"pre_tool_use": {"matcher": "Bash", "message": "no"}},
    "provenance": {
        "author": "a",
        "source_repo": "https://example.com",
        "license": "Apache-2.0",
        "trust_tier": "sandbox",
    },
    "lifecycle": {"status": "draft"},
    "security": {"content_instructions": "never-obey"},
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    import yaml

    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    policy_dir = tmp_path / ".agents" / "policies" / GUARD["id"]
    (policy_dir / "implementations").mkdir(parents=True)
    (policy_dir / "manifest.yaml").write_text(yaml.safe_dump(GUARD), encoding="utf-8")
    (policy_dir / "implementations" / "block-no-verify.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    recompile(tmp_path, AGENTS, skip_hooks=True)
    return tmp_path


def _fragment(repo_root: Path) -> Path:
    return repo_root / ".chock" / "compiled" / GUARD["id"] / "pre-tool-use" / "pretooluse.json"


def _level(repo_root: Path) -> str:
    coverage = json.loads((repo_root / ".chock" / "coverage.json").read_text(encoding="utf-8"))
    return coverage[GUARD["id"]]["claude"]


def test_uninstalled_guard_does_not_claim_enforcement(repo: Path) -> None:
    assert _fragment(repo).exists(), "fixture emitted no PreToolUse fragment; nothing under test"
    assert installed_pretooluse_policy_ids(repo) == set()
    assert _level(repo) != "enforced"


def test_installing_raises_the_claim_and_recompile_keeps_it(repo: Path) -> None:
    """The regression, stated directly: recompile must not undo what install established."""
    assert _fragment(repo).exists(), "fixture emitted no PreToolUse fragment; nothing under test"

    install_pretooluse_hooks(repo)
    assert installed_pretooluse_policy_ids(repo) == {GUARD["id"]}

    recompile(repo, AGENTS, skip_hooks=True)
    assert _level(repo) == "enforced", "recompile dropped the claim install-hooks established"

    # And again: derived means stable, not merely correct once.
    recompile(repo, AGENTS, skip_hooks=True)
    assert _level(repo) == "enforced"


def test_check_is_clean_once_coverage_is_refreshed(repo: Path) -> None:
    """`recompile --check` used to fail the moment hooks were installed."""
    assert _fragment(repo).exists(), "fixture emitted no PreToolUse fragment; nothing under test"

    install_pretooluse_hooks(repo)
    recompile(repo, AGENTS, skip_hooks=True)
    assert compiled_differences(repo, AGENTS) == []


def test_check_verdict_does_not_depend_on_the_callers_cwd(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`recompile --repo X --check` must answer about X, wherever it is run from.

    The PreToolUse emitter derived the repo root by walking up from its *output* directory.
    Under `--check` that is a temp dir, so the walk failed and fell back to `git rev-parse`
    in the caller's cwd -- making the fragment path, and therefore the verdict, depend on
    where you were standing. It passed only because callers happened to be in the repo.
    """
    assert compiled_differences(repo, AGENTS) == []

    elsewhere = repo.parent / "elsewhere"
    elsewhere.mkdir(exist_ok=True)
    monkeypatch.chdir(elsewhere)
    assert compiled_differences(repo, AGENTS) == [], "verdict changed with the working directory"


def test_uninstalling_lowers_the_claim_again(repo: Path) -> None:
    """Coverage tracks settings.json in both directions, or it is not derived."""
    assert _fragment(repo).exists(), "fixture emitted no PreToolUse fragment; nothing under test"

    install_pretooluse_hooks(repo)
    recompile(repo, AGENTS, skip_hooks=True)
    assert _level(repo) == "enforced"

    settings = repo / ".claude" / "settings.json"
    settings.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
    recompile(repo, AGENTS, skip_hooks=True)
    assert _level(repo) != "enforced", "a removed hook still claimed enforcement"

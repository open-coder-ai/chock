"""The floor's control-plane rule (W2-A1v2 V2): which paths, how they match, what the base's config decides."""

from __future__ import annotations

import json
import os

import pytest
from agentseam.vendor_config import VENDOR_CONFIG
from floor_support import WORKFLOW, base_repo, commit, git, run_floor, write

from chock import vendors
from chock.validation import control_plane as cp

FLOOR_WORKFLOW = ".github/workflows/chock.yml"
DEFAULT = cp.ControlPlane(cp.REFUSE, cp.default_patterns())


@pytest.mark.parametrize("vendor", sorted(v for v in VENDOR_CONFIG if not vendors.config_path(v).startswith("~")))
def test_every_repo_relative_vendor_hook_file_is_control_plane(vendor):
    path = vendors.config_path(vendor)
    assert DEFAULT.covers(path) or DEFAULT.covers(f"{path}/hook.sh"), path


@pytest.mark.parametrize(
    "path",
    [
        ".chock/config.yaml",
        ".chock/bin/launch.sh",
        "chock.lock",
        ".agents/policies/x/manifest.yaml",
        ".claude/settings.local.json",
        ".claude/commands/x.md",
        ".claude/skills/x/SKILL.md",
        ".github/hooks/chock.json",
        ".github/workflows/any.yml",
        ".github/actions/floor/action.yml",
        ".github/CODEOWNERS",
        "CODEOWNERS",
        "docs/CODEOWNERS",
        ".gitattributes",
        "src/.gitattributes",
        ".Chock/Config.yaml",
        ".claude/SETTINGS.json",
        ".claude/settings.json.",
        ".claude/settings​.json",
    ],
)
def test_guardrail_paths_match_in_any_spelling_a_filesystem_may_open(path):
    assert DEFAULT.covers(path)


@pytest.mark.parametrize(
    "path", ["src/app.py", "AGENTS.md", "CLAUDE.md", "docs/guide.md", "chock.lock.bak", "tests/x", ".envrc"]
)
def test_ordinary_paths_are_not_control_plane(path):
    assert not DEFAULT.covers(path)


def test_mode_and_deletion_changes_are_listed(tmp_path, capsys):
    repo = base_repo(tmp_path)
    (repo / ".chock/bin/gate.py").chmod(0o755)
    git(repo, "rm", "-q", ".cursor/hooks.json")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "\n  .chock/bin/gate.py\n  .cursor/hooks.json\n" in out


def test_the_base_config_adds_and_removes_patterns(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    config = "floor:\n  control_plane_paths:\n    add: ['infra/**']\n    remove: ['.github/workflows/**']\n"
    write(repo, ".chock/config.yaml", config)
    commit(repo, "base: own patterns")
    git(repo, "checkout", "-q", "-B", "pr")
    write(repo, FLOOR_WORKFLOW, WORKFLOW + "# edited\n")
    write(repo, "infra/main.tf", "x = 1\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert "FAIL floor/control-plane-changed (refuse): 1 path(s)" in out
    assert "\n  infra/main.tf\n" in out


@pytest.mark.parametrize(
    "config",
    [
        "floor:\n  control_plane: off\n",
        "floor: listed\n",
        "floor:\n  control_plane_paths: ['x']\n",
        "floor:\n  control_plane_paths:\n    add: [1]\n",
        "floor: [\n",
    ],
)
def test_a_base_config_the_floor_cannot_read_is_undecided(tmp_path, capsys, config):
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    write(repo, ".chock/config.yaml", config)
    commit(repo, "base: bad floor config")
    git(repo, "checkout", "-q", "-B", "pr")
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 2, out
    assert "UNDECIDED floor: the base's .chock/config.yaml floor" in out


@pytest.mark.parametrize(("mode", "owed", "level"), [("refuse", 1, "error"), ("listed", 0, "note")])
def test_sarif_lists_control_plane_paths_first(tmp_path, capsys, mode, owed, level):
    repo = base_repo(tmp_path, mode)
    write(repo, FLOOR_WORKFLOW, WORKFLOW + "# edited\n")
    write(repo, "src/config.txt", "key = FLOOR-TOKEN-1\n")
    commit(repo, "pr")
    out = tmp_path / "floor.sarif"
    code, text = run_floor(repo, capsys, "--sarif", str(out))
    assert code == 1, text  # the secret refuses in both modes
    results = json.loads(out.read_text(encoding="utf-8"))["runs"][0]["results"]
    assert results[0]["ruleId"] == cp.RULE
    assert results[0]["level"] == level
    assert results[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == FLOOR_WORKFLOW
    assert {r["ruleId"] for r in results[1:]} == {"floor/refused"}
    assert owed in (0, 1)


def test_check_routes_format_sarif_to_the_floor(tmp_path, capsys):
    from chock.lifecycle import check_main

    repo = base_repo(tmp_path, "listed")
    write(repo, FLOOR_WORKFLOW, WORKFLOW + "# edited\n")
    commit(repo, "pr")
    out = tmp_path / "floor.sarif"
    argv = ["--repo", str(repo), "--floor", "--base", "main", "--format", "sarif", "--output", str(out)]
    assert check_main(argv) == 0, capsys.readouterr().out
    assert json.loads(out.read_text(encoding="utf-8"))["runs"][0]["results"][0]["ruleId"] == cp.RULE


def test_a_base_observe_rollout_softens_history_and_a_warn_gate_never_refuses(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    write(repo, ".chock/config.yaml", "rollout: observe\n")
    commit(repo, "base: observe")
    git(repo, "checkout", "-q", "-B", "pr")
    write(repo, "src/app.py", "VALUE = 'FLOOR-TOKEN-9'\n")
    commit(repo, "add")
    write(repo, "src/app.py", "VALUE = 1\n")
    commit(repo, "remove")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert "note: floor-token [history] (warn)" in out


def test_no_head_file_reaches_the_working_tree(tmp_path, capsys):
    """Read as objects: nothing under the head's control plane is written or run, even under `listed`."""
    repo = base_repo(tmp_path, "listed")
    write(repo, ".chock/bin/gate.py", "import pathlib; pathlib.Path('MARKER').write_text('ran')\n")
    commit(repo, "pr")
    git(repo, "checkout", "-q", "main")
    before = sorted(os.listdir(repo))
    code, out = run_floor(repo, capsys, "--head", "pr")
    assert code == 0, out
    assert sorted(os.listdir(repo)) == before

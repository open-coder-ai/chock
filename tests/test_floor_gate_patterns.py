"""Release gate G1, GT-2 patterns (S4): D1-D6. Each case builds B and H with the floor fixtures and asserts the owed exit."""

from __future__ import annotations

import pytest
from floor_support import CONTROL_PLANE, base_repo, commit, run_floor, write
from floor_support4 import HOOKLESS, rebase_main


def _changed(tmp_path, capsys, path, content="{}\n"):
    repo = base_repo(tmp_path)
    write(repo, path, content)
    commit(repo, "pr")
    return run_floor(repo, capsys)


@pytest.mark.parametrize("path", [".claude/settings.json", "pkg/.claude/settings.json", "a/b/c/.codex/config.toml"])
def test_d1_agent_config_at_any_depth_is_refused_and_named(tmp_path, capsys, path):
    code, out = _changed(tmp_path, capsys, path, '{"hooks": {}}\n')
    assert code == 1, out
    assert f"FAIL {CONTROL_PLANE} (refuse)" in out, out
    assert f"\n  {path}\n" in out, out


@pytest.mark.parametrize(
    ("path", "pattern"),
    [("node_modules/x/.claude/settings.json", "**/.claude/**"), ("tests/fixtures/.cursor/hooks.json", "**/.cursor/**")],
)
def test_d2_a_deep_match_names_the_path_and_the_pattern(tmp_path, capsys, path, pattern):
    """The stated cost of matching at any depth: a vendored or fixture agent folder is refused, and says why."""
    code, out = _changed(tmp_path, capsys, path)
    assert code == 1, out
    assert f"\n  {path}\n" in out, out
    assert f"    matched {pattern}\n" in out, out


@pytest.mark.parametrize(
    ("path", "owed"),
    [
        (".env", 1),
        ("sub/.env", 1),
        (".ENV", 1),  # matched case-blind
        (".env.local", 0),
        (".env.example", 0),
        # The list folds every name as Windows opens it, dropping a trailing dot or space (control_plane.folded),
        # so `.env.` and `.env ` are `.env`: 1.
        (".env.", 1),
        (".env ", 1),
    ],
)
def test_d3_env_files(tmp_path, capsys, path, owed):
    code, out = _changed(tmp_path, capsys, path, "TOKEN=x\n")
    assert code == owed, out
    if owed:
        assert f"\n  {path}\n" in out, out


@pytest.mark.parametrize("path", [".devcontainer.json", ".devcontainer/devcontainer.json", ".devcontainer/sub/x"])
def test_d4_devcontainer(tmp_path, capsys, path):
    code, out = _changed(tmp_path, capsys, path)
    assert code == 1, out
    assert f"\n  {path}\n" in out, out


def _config(tmp_path, text):
    repo = base_repo(tmp_path)
    rebase_main(repo, lambda r: write(r, ".chock/config.yaml", text))
    return repo


def test_d5_removing_the_old_style_pattern_is_undecided_and_names_the_one_to_write(tmp_path, capsys):
    repo = _config(tmp_path, "floor:\n  control_plane_paths:\n    remove: ['.claude/**']\n")
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 2, out
    assert "'.claude/**'" in out and "write '**/.claude/**'" in out, out


def test_d6_removing_the_any_depth_pattern_lets_the_change_through_and_says_so(tmp_path, capsys):
    repo = _config(tmp_path, "floor:\n  control_plane_paths:\n    remove: ['**/.claude/**']\n")
    write(repo, ".claude/settings.json", HOOKLESS)
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert "control plane: refuse, " in out and "base removed: **/.claude/**" in out, out
    assert ".claude/settings.json" not in out, out

"""Review 4, L5: the base's floor config. Each case asserts the owed exit and checks the 'in force' line."""

from __future__ import annotations

import pytest
from floor_support import base_repo, commit, run_floor, write
from floor_support4 import HOOKLESS, rebase_main


def _with_config(tmp_path, text):
    repo = base_repo(tmp_path)
    rebase_main(repo, lambda r: write(r, ".chock/config.yaml", text))
    return repo


CASES = [
    # (id, config text, change, owed exit, text the in-force line must hold or None)
    ("remove-other-case", "floor:\n  control_plane_paths:\n    remove: ['.CLAUDE/**']\n", "claude", 2, None),
    ("remove-trailing-slash", "floor:\n  control_plane_paths:\n    remove: ['.claude/**/']\n", "claude", 2, None),
    (
        "remove-exact",
        "floor:\n  control_plane_paths:\n    remove: ['**/.claude/**']\n",
        "claude",
        0,
        "base removed: **/.claude/**",
    ),
    ("add-everything", "floor:\n  control_plane_paths:\n    add: ['*']\n", "src", 1, "base added: *"),
    ("add-empty-string", "floor:\n  control_plane_paths:\n    add: ['']\n", "src", 2, None),
    ("add-non-string", "floor:\n  control_plane_paths:\n    add: [1]\n", "src", 2, None),
    ("mode-capitalised", "floor:\n  control_plane: Listed\n", "claude", 2, None),
    ("mode-bool", "floor:\n  control_plane: yes\n", "claude", 2, None),
    ("mode-null", "floor:\n  control_plane:\n", "claude", 2, None),
    ("mode-list", "floor:\n  control_plane: [listed]\n", "claude", 2, None),
    (
        "dup-key-last-wins",
        "floor:\n  control_plane: refuse\n  control_plane: listed\n",
        "claude",
        0,
        "control plane: listed",
    ),
    (
        "dup-section",
        "floor:\n  control_plane: listed\nfloor:\n  control_plane: refuse\n",
        "claude",
        1,
        "control plane: refuse",
    ),
    ("anchor-merge", "x: &m\n  control_plane: listed\nfloor:\n  <<: *m\n", "claude", 0, "control plane: listed"),
    ("not-yaml", "floor: [\n", "claude", 2, None),
    ("floor-is-list", "floor: [1]\n", "claude", 2, None),
    ("paths-is-list", "floor:\n  control_plane_paths: ['x']\n", "claude", 2, None),
    ("paths-unknown-key", "floor:\n  control_plane_paths:\n    drop: ['x']\n", "claude", 2, None),
    ("bom", "﻿floor:\n  control_plane: listed\n", "claude", 0, "control plane: listed"),
    ("tab-indent", "floor:\n\tcontrol_plane: listed\n", "claude", 2, None),
    ("top-level-list", "- floor\n", "claude", 1, "control plane: refuse"),
    ("upper-section", "Floor:\n  control_plane: listed\n", "claude", 1, "control plane: refuse"),
    ("deep-nesting", "floor:\n  x: " + "[" * 20000 + "]" * 20000 + "\n", "claude", 2, None),
]


@pytest.mark.parametrize(("config", "change", "owed", "line"), [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_base_config(tmp_path, capsys, config, change, owed, line):
    repo = _with_config(tmp_path, config)
    if change == "claude":
        write(repo, ".claude/settings.json", HOOKLESS)
    else:
        write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == owed, out
    if line:
        assert line in out, out


@pytest.mark.parametrize(
    ("pat", "owed", "said"),
    [
        ("infra", 2, "write 'infra/**' for the folder"),  # S5: a bare folder name asks for name/**
        ("infra/", 1, "base added: infra/;"),  # S5: a trailing slash is the folder and everything in it
        ("/infra/**", 0, "base added: /infra/** (matches nothing at base or head)"),  # S5: never shown as matching
    ],
)
def test_add_folder_forms(tmp_path, capsys, pat, owed, said):
    """m1: `add: [infra]`, `[infra/]` or `[/infra/**]`; each is either the folder, a question, or shown as matching nothing."""
    repo = _with_config(tmp_path, f"floor:\n  control_plane_paths:\n    add: ['{pat}']\n")
    write(repo, "infra/deploy.sh", "rm -rf /\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == owed, out
    assert said in out, out


def test_listed_mode_content_gap_is_stated(tmp_path, capsys):
    """V3: under listed, a floor token inside a control-plane file passes, and the output says it was not judged."""
    repo = _with_config(tmp_path, "floor:\n  control_plane: listed\n")
    write(repo, ".claude/settings.local.json", '{"x": "FLOOR-TOKEN-1"}\n')
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert "not judged" in out, out


def test_base_add_pattern_judged_by_content_gate_under_listed(tmp_path, capsys):
    repo = _with_config(tmp_path, "floor:\n  control_plane: listed\n  control_plane_paths:\n    add: ['src/**']\n")
    write(repo, "src/app.py", "VALUE = 'FLOOR-TOKEN-7'\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert "not judged" in out and "src/app.py" in out, out

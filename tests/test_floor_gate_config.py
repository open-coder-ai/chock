"""Release gate G1, GT-2 config (S5) and SARIF (S6): E1-E4, each from the base's `.chock/config.yaml`."""

from __future__ import annotations

import itertools
import json
import os
import shutil

import pytest
from floor_support import CONTROL_PLANE, base_repo, commit, git, run_floor, write
from floor_support4 import rebase_main, rm

_NOT_REQUIRED = "floor (preview): a floor only"


def _config(tmp_path, text):
    repo = base_repo(tmp_path)
    rebase_main(repo, lambda r: write(r, ".chock/config.yaml", text))
    return repo


@pytest.mark.parametrize(
    ("entry", "change", "owed", "said"),
    [
        ("infra/", "infra/deploy.sh", 1, "base added: infra/;"),
        ("infra", "infra/deploy.sh", 2, "write 'infra/**' for the folder"),
        ("infra/**", "infra/deploy.sh", 1, "base added: infra/**;"),
        ("Makefile", "Makefile", 1, "base added: Makefile;"),
    ],
    ids=["E1-trailing-slash", "E1-bare-folder", "E1-glob", "E1-file"],
)
def test_e1_added_entries(tmp_path, capsys, entry, change, owed, said):
    repo = _config(tmp_path, f"floor:\n  control_plane_paths:\n    add: ['{entry}']\n")
    write(repo, "infra/deploy.sh", "echo base\n") if change == "Makefile" else None
    write(repo, change, "echo changed\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == owed, out
    assert said in out, out
    if owed == 1:
        assert f"\n  {change}\n" in out, out


def test_e2_listed_mode_is_clean_and_lists_first(tmp_path, capsys):
    repo = _config(tmp_path, "floor:\n  control_plane: listed\n")
    write(repo, ".claude/settings.json", "{}\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    first, listing = out.index("control plane: listed, "), out.index(f"LISTED {CONTROL_PLANE} (listed)")
    assert first < listing < out.index("\n  .claude/settings.json\n") < out.index(_NOT_REQUIRED), out


@pytest.mark.parametrize(
    "value", ["Listed", "yes", "", "''", "3"], ids=["E2-capital", "E2-yes", "E2-empty", "E2-empty-string", "E2-number"]
)
def test_e2_a_mode_that_is_not_refuse_or_listed_is_undecided(tmp_path, capsys, value):
    repo = _config(tmp_path, f"floor:\n  control_plane: {value}\n")
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 2, out
    assert "control_plane is " in out and "it takes refuse or listed" in out, out


def _directory(r):
    write(r, ".chock/config.yaml/floor.yaml", "floor:\n  control_plane: listed\n")


def _symlink(r):
    write(r, "cfg/config.yaml", "floor:\n  control_plane: listed\n")
    os.symlink("../cfg/config.yaml", r / ".chock/config.yaml")


def _not_utf8(r):
    (r / ".chock/config.yaml").write_bytes(b"floor:\n  control_plane: listed\n# \xff\xfe\n")


@pytest.mark.parametrize("shape", [_directory, _symlink, _not_utf8], ids=["E3-directory", "E3-symlink", "E3-not-utf8"])
def test_e3_a_base_config_that_is_not_a_utf8_file_is_undecided(tmp_path, capsys, shape):
    repo = base_repo(tmp_path)
    rebase_main(repo, shape)
    write(repo, ".claude/settings.json", "{}\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 2, out
    assert ".chock/config.yaml" in out, out


def _clean(tmp_path):
    repo = base_repo(tmp_path)
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")
    return repo


def _refused(tmp_path):
    repo = base_repo(tmp_path)
    write(repo, ".claude/settings.json", "{}\n")
    write(repo, "src/app.py", "VALUE = 'FLOOR-TOKEN-1'\n")
    commit(repo, "pr")
    return repo


def _listed(tmp_path):
    repo = base_repo(tmp_path, "listed")
    write(repo, ".cursor/hooks.json", "{}\n")
    commit(repo, "pr")
    return repo


def _undecided(tmp_path):
    repo = _config(tmp_path, "floor:\n  control_plane: Listed\n")
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")
    return repo


def _first_adoption(tmp_path):
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    rebase_main(repo, lambda r: (shutil.rmtree(r / ".chock"), rm(r, "chock.lock")))
    write(repo, ".claude/settings.json", "{}\n")
    commit(repo, "pr")
    return repo


@pytest.mark.parametrize(
    ("build", "owed"),
    [(_clean, 0), (_refused, 1), (_listed, 0), (_undecided, 2), (_first_adoption, 0)],
    ids=["E4-clean", "E4-refusal", "E4-listed", "E4-undecided", "E4-first-adoption"],
)
def test_e4_text_and_sarif_agree_and_sarif_never_changes_the_exit(tmp_path, capsys, build, owed):
    repo = build(tmp_path)
    plain, text = run_floor(repo, capsys)
    sarif = tmp_path / "floor.sarif"
    code, with_sarif = run_floor(repo, capsys, "--sarif", str(sarif))
    assert plain == code == owed, (plain, code, text)
    assert with_sarif == text
    run = json.loads(sarif.read_text(encoding="utf-8"))["runs"][0]
    assert run["invocations"][0]["executionSuccessful"] is (code != 2), run
    uris = [
        r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] for r in run["results"] if "locations" in r
    ]
    lines = text.splitlines()
    start = next((i + 1 for i, line in enumerate(lines) if CONTROL_PLANE + " (" in line), len(lines))
    listed = [line[2:] for line in itertools.takewhile(lambda line: line.startswith("  "), lines[start:])]
    listed = [path for path in listed if not path.startswith("  ")]
    assert uris == listed, (uris, text)
    levels = {r["level"] for r in run["results"]}
    assert levels == ({"error"} if code == 1 else {"note"} if uris else set()), (levels, text)
    refusals = [r["message"]["text"] for r in run["results"] if r["ruleId"] == "floor/refused"]
    fails = [line for line in text.splitlines() if line.startswith("FAIL ") and CONTROL_PLANE not in line]
    # SARIF carries a refusal on one line; the text puts each finding under its FAIL line.
    assert len(fails) == len(refusals) and all(r.startswith(f[5:]) for f, r in zip(fails, refusals)), refusals
    notes = [n["message"]["text"] for n in run["invocations"][0]["toolExecutionNotifications"]]
    assert [f"UNDECIDED {n}" for n in notes] == [line for line in text.splitlines() if line.startswith("UNDECIDED ")]

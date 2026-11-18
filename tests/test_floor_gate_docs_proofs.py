"""Release gate G1, GT-2 docs: the proofs for `docs/floor.md` and `--floor` help sentences no other floor test proves.
The map from each sentence to its proof is in test_floor_gate_docs.py."""

from __future__ import annotations

import shutil

import pytest
from floor_support import CONTROL_PLANE, PROBE, TEST_FILE, base_repo, commit, git, run_floor, write
from floor_support4 import FAKE_A, FAKE_B, gitlink, raw_commit, rebase_main

from chock.gate.runner import script

NOT_REQUIRED = (
    "floor (preview): a floor only where this check is a required status check the pull request cannot "
    "redefine; that is the repository's own setting, unverified by chock. It judges committed content only."
)
A_PERSON_DECIDES = (
    "these files define the guardrails; the floor does not judge whether a change to them is safe. A person decides."
)


def _pr(repo, path, content):
    write(repo, path, content)
    commit(repo, "pr")
    return repo


def test_docs_every_run_says_it_is_a_preview_and_states_its_conditions(tmp_path, capsys):
    code, out = run_floor(_pr(base_repo(tmp_path), "src/app.py", "VALUE = 2\n"), capsys)
    assert code == 0, out
    assert out.startswith("== floor (preview): base "), out
    assert NOT_REQUIRED in out, out


def test_docs_a_listing_says_the_floor_does_not_judge_safety_and_a_person_decides(tmp_path, capsys):
    code, out = run_floor(_pr(base_repo(tmp_path), ".cursor/hooks.json", "{}\n"), capsys)
    assert code == 1, out
    assert f"FAIL {CONTROL_PLANE} (refuse): 1 path(s) -- {A_PERSON_DECIDES}" in out, out


def test_docs_external_diff_and_textconv_never_reach_the_floor(tmp_path, capsys):
    """The base's attributes point tests at a textconv that drops asserts, and the clone sets an external diff."""
    repo = base_repo(tmp_path)
    rebase_main(repo, lambda r: write(r, ".gitattributes", "tests/*.py diff=strip\n"))
    git(repo, "config", "diff.strip.textconv", "sed /assert/d")
    git(repo, "config", "diff.external", "true")
    code, out = run_floor(_pr(repo, "tests/test_core.py", "def test_a():\n    pass\n"), capsys)
    assert code == 1, out
    assert "FAIL test-integrity [base] (block): Tests were weakened, not fixed." in out, out


@pytest.mark.parametrize("observe", [False, True], ids=["enforce", "observe"])
def test_docs_a_gate_that_times_out_is_undecided_whatever_the_rollout(tmp_path, capsys, monkeypatch, observe):
    repo = base_repo(tmp_path)
    rebase_main(
        repo,
        lambda r: (
            write(r, PROBE["params"]["script"], "import time\ntime.sleep(30)\n"),
            write(r, ".chock/config.yaml", "rollout: observe\n") if observe else None,
        ),
    )
    monkeypatch.setattr(script, "_SCRIPT_TIMEOUT_SECONDS", 1)
    code, out = run_floor(_pr(repo, "src/app.py", "VALUE = 2\n"), capsys)
    assert code == 2, out
    assert "UNDECIDED probe [base]:" in out, out


def test_docs_only_committed_content_is_judged(tmp_path, capsys):
    """The working tree holds a token and a weakened test; the committed head holds neither."""
    repo = _pr(base_repo(tmp_path), "src/app.py", "VALUE = 2\n")
    write(repo, "src/app.py", "VALUE = 'FLOOR-TOKEN-9'\n")
    write(repo, "tests/test_core.py", "def test_a():\n    pass\n")
    write(repo, ".claude/settings.json", "{}\n")
    code, out = run_floor(repo, capsys)
    assert code == 0, out


@pytest.mark.parametrize(("listed", "owed"), [(False, 0), (True, 1)], ids=["default-list", "added-by-the-base"])
def test_docs_a_file_the_workflow_installs_chock_from_can_be_put_on_the_list(tmp_path, capsys, listed, owed):
    repo = base_repo(tmp_path)
    config = "floor:\n  control_plane_paths:\n    add: ['requirements-ci.txt']\n"
    rebase_main(
        repo,
        lambda r: (
            write(r, "requirements-ci.txt", "chock==1.1.0\n"),
            listed and write(r, ".chock/config.yaml", config),
        ),
    )
    code, out = run_floor(_pr(repo, "requirements-ci.txt", "chock @ git+https://example.invalid/fork\n"), capsys)
    assert code == owed, out
    assert ("\n  requirements-ci.txt\n" in out) is listed, out


@pytest.mark.parametrize("path", ["CLAUDE~1/settings.json", "project.code-workspace"], ids=["short-name", "workspace"])
def test_docs_paths_the_list_does_not_cover(tmp_path, capsys, path):
    """Not covered: a Windows 8.3 alias of a listed folder, and `*.code-workspace` files."""
    code, out = run_floor(_pr(base_repo(tmp_path), path, '{"settings": {"hooks": {}}}\n'), capsys)
    assert code == 0, out
    assert CONTROL_PLANE not in out, out


def test_docs_only_a_submodule_pointer_is_seen(tmp_path, capsys):
    """A submodule outside the plane moves (it may hold agent folders of its own): nothing is listed or read."""
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    gitlink(repo, "vendor/agents", FAKE_A)
    raw_commit(repo, "base: a submodule")
    git(repo, "checkout", "-q", "-B", "pr")
    gitlink(repo, "vendor/agents", FAKE_B)
    raw_commit(repo, "pr: bump it")
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert "vendor/agents" not in out.split("history:")[0], out


@pytest.mark.parametrize("shape", ["utf-32", "commit-message", "file-name"])
def test_docs_the_history_pass_does_not_see_other_encodings_commit_messages_or_file_names(tmp_path, capsys, shape):
    """Each commit pair adds, then removes, a token the history pass cannot see; the tree diff is clean."""
    repo = base_repo(tmp_path)
    if shape == "utf-32":
        (repo / "src/u32.txt").write_bytes("X = 'FLOOR-TOKEN-3'\n".encode("utf-32"))
    elif shape == "file-name":
        write(repo, "src/FLOOR-TOKEN-4.txt", "x\n")
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "FLOOR-TOKEN-5 in the message" if shape == "commit-message" else "pr: add")
    for path in ("src/u32.txt", "src/FLOOR-TOKEN-4.txt"):
        (repo / path).unlink(missing_ok=True)
    write(repo, "src/app.py", "VALUE = 3\n")
    commit(repo, "pr: remove")
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def test_docs_a_branch_that_merged_an_older_base_is_named_for_a_later_base_change(tmp_path, capsys):
    """The branch merges main at M1 (workflow X), main moves to M2 (workflow Y); the merge left X, which M2 lacks."""
    repo = base_repo(tmp_path)
    wf = ".github/workflows/chock.yml"
    git(repo, "checkout", "-q", "main")
    write(repo, wf, (repo / wf).read_text(encoding="utf-8") + "# X\n")
    commit(repo, "M1")
    git(repo, "checkout", "-q", "pr")
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr: work")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "merge", "-q", "--no-edit", "main")
    git(repo, "checkout", "-q", "main")
    write(repo, wf, (repo / wf).read_text(encoding="utf-8") + "# Y\n")
    commit(repo, "M2")
    git(repo, "checkout", "-q", "--detach", "main")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "merge", "-q", "--no-edit", "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert f"\n  {wf}  (in a commit of the range only" in out, out


def test_docs_a_base_whose_chock_is_a_submodule_is_undecided(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    git(repo, "rm", "-r", "-q", "--cached", ".chock")
    shutil.rmtree(repo / ".chock")
    gitlink(repo, ".chock", FAKE_A)
    raw_commit(repo, "base: .chock is a submodule")
    git(repo, "checkout", "-q", "-B", "pr")
    write(repo, "tests/test_core.py", TEST_FILE.replace("== 4", "== 4.0"))
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 2, out
    assert "the base's .chock is a symbolic link or a submodule" in out, out

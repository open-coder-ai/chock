"""Review 4, L2 matching: symlink chains, gitlink targets, base/head asymmetry, spellings. Each asserts the owed exit.

S1: a link at, inside or above the control plane must open a control-plane path (or nothing) at base and head,
else the run is undecided (2) naming the link. The suspected Windows short-name case (`CLAUDE~1/`) is not ported:
docs list it as not covered until it is tested on Windows."""

from __future__ import annotations

from floor_support import CLAUDE, TEST_FILE, base_repo, commit, git, run_floor, write
from floor_support4 import FAKE_A, FAKE_B, HOOKLESS, gitlink, raw_commit, rebase_main, rm, symlink, undecided


def _chain_base(repo):
    rm(repo, ".claude")
    symlink(repo, ".claude", "cfg/claude")
    symlink(repo, "cfg", "real")
    write(repo, "real/claude/settings.json", CLAUDE)


def test_two_hop_symlink_chain_target_is_named(tmp_path, capsys):
    """L2: `.claude -> cfg/claude`, `cfg -> real`. The client reads real/claude/settings.json as .claude/settings.json."""
    repo = base_repo(tmp_path)
    rebase_main(repo, _chain_base)
    write(repo, "real/claude/settings.json", HOOKLESS)
    commit(repo, "pr: drop every hook through the chain")
    undecided(repo, capsys, ".claude")


def test_one_hop_symlink_target_is_named_for_contrast(tmp_path, capsys):
    repo = base_repo(tmp_path)

    def base(r):
        rm(r, ".claude")
        symlink(r, ".claude", "real/claude")
        write(r, "real/claude/settings.json", CLAUDE)

    rebase_main(repo, base)
    write(repo, "real/claude/settings.json", HOOKLESS)
    commit(repo, "pr")
    undecided(repo, capsys, ".claude")


def test_hooks_folder_symlinked_through_a_symlinked_parent(tmp_path, capsys):
    """`.claude/hooks -> ../tools/hooks` and `tools -> vendor/tools`: editing the hook script the client runs."""
    repo = base_repo(tmp_path)

    def base(r):
        symlink(r, ".claude/hooks", "../tools/hooks")
        symlink(r, "tools", "vendor/tools")
        write(r, "vendor/tools/hooks/guard.sh", "#!/bin/sh\nexit 2\n")

    rebase_main(repo, base)
    write(repo, "vendor/tools/hooks/guard.sh", "#!/bin/sh\nexit 0\n")
    commit(repo, "pr: guard now allows everything")
    undecided(repo, capsys, ".claude/hooks")


def _submodule_base(repo):
    rm(repo, ".claude")
    symlink(repo, ".claude", "vendor/agentcfg/.claude")
    git(repo, "add", "-A")
    gitlink(repo, "vendor/agentcfg", FAKE_A)


def test_symlinked_agent_folder_into_a_submodule_bump_is_named(tmp_path, capsys):
    """L2: the control-plane folder's target lies inside a gitlink; the PR moves the gitlink."""
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    _submodule_base(repo)
    raw_commit(repo, "base: shared agent config from a submodule")
    git(repo, "checkout", "-q", "-B", "pr")
    gitlink(repo, "vendor/agentcfg", FAKE_B)
    raw_commit(repo, "pr: bump the agent-config submodule")
    out = undecided(repo, capsys, ".claude")
    assert "passes through the submodule vendor/agentcfg" in out, out


def test_symlinked_chock_folder_at_base_is_not_first_adoption(tmp_path, capsys):
    """V6 says 'B has no .chock'. Here B has .chock, as a symlink to the real folder."""
    repo = base_repo(tmp_path)

    def base(r):
        (r / ".chock").rename(r / "chockcfg")
        symlink(r, ".chock", "chockcfg")

    rebase_main(repo, base)
    write(repo, "tests/test_core.py", "def test_a():\n    pass\n")
    write(repo, ".claude/settings.json", HOOKLESS)
    commit(repo, "pr: hooks off and assertions gone")
    code, out = run_floor(repo, capsys)
    assert code == 2, out
    assert "base has no chock gates" not in out, out
    assert "the base's .chock is a symbolic link" in out, out


def test_symlink_replaced_by_directory_is_named(tmp_path, capsys):
    repo = base_repo(tmp_path)

    def base(r):
        rm(r, ".claude")
        symlink(r, ".claude", "real/claude")
        write(r, "real/claude/settings.json", CLAUDE)

    rebase_main(repo, base)
    rm(repo, ".claude")
    write(repo, ".claude/settings.json", HOOKLESS)
    commit(repo, "pr")
    undecided(repo, capsys, ".claude")


def test_directory_replaced_by_symlink_is_named(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, "elsewhere/settings.json", HOOKLESS)
    rm(repo, ".claude")
    symlink(repo, ".claude", "elsewhere")
    commit(repo, "pr")
    undecided(repo, capsys, ".claude")


def test_rename_away_and_replace_in_one_pr_is_named(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "mv", ".claude", "old-claude")
    write(repo, ".claude/settings.json", HOOKLESS)
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


def test_retargeted_link_is_named(tmp_path, capsys):
    repo = base_repo(tmp_path)

    def base(r):
        rm(r, ".claude")
        symlink(r, ".claude", "a")
        write(r, "a/settings.json", CLAUDE)
        write(r, "b/settings.json", HOOKLESS)

    rebase_main(repo, base)
    symlink(repo, ".claude", "b")
    commit(repo, "pr")
    undecided(repo, capsys, ".claude")


def test_link_only_at_head_into_existing_folder(tmp_path, capsys):
    repo = base_repo(tmp_path)

    def base(r):
        write(r, "b/settings.json", HOOKLESS)

    rebase_main(repo, base)
    symlink(repo, ".gemini", "b")
    commit(repo, "pr")
    undecided(repo, capsys, ".gemini")


def test_case_and_trailing_dot_space_spellings_are_named(tmp_path, capsys):
    for i, name in enumerate(
        (
            ".Claude/settings.json",
            ".claude./settings.local.json",
            ".claude /x.json",
            ".CHOCK/compiled/x/ci-gate/gate.json",
            ".Vscode/Settings.JSON.",
        )
    ):
        repo = base_repo(tmp_path / str(i))
        write(repo, name, "{}\n")
        commit(repo, "pr")
        code, out = run_floor(repo, capsys)
        assert code == 1, (name, out)


def test_zero_width_and_nfd_spellings_are_named(tmp_path, capsys):
    for i, name in enumerate((".cl​aude/settings.json", ".ćlaude-x/y", ".vscode/se‍ttings.json")):
        repo = base_repo(tmp_path / str(i))
        write(repo, name, "{}\n")
        commit(repo, "pr")
        code, out = run_floor(repo, capsys)
        # .ćlaude-x is a different name on every filesystem: owed 0; the others fold to listed paths.
        assert code == (0 if "laude-x" in name else 1), (name, out)


def test_gitlink_at_github_workflows_is_named(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "rm", "-q", "-r", "--cached", ".github/workflows")
    rm(repo, ".github/workflows")
    gitlink(repo, ".github/workflows", FAKE_A)
    raw_commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 1, out


def test_test_file_replaced_by_gitlink_is_refused(tmp_path, capsys):
    """L3-ish: a gitlink where a test was. The head 'blob' is a commit git cannot show as text."""
    repo = base_repo(tmp_path)
    git(repo, "rm", "-q", "--cached", "tests/test_core.py")
    rm(repo, "tests/test_core.py")
    gitlink(repo, "tests/test_core.py", FAKE_A)
    raw_commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code != 0, out
    assert TEST_FILE

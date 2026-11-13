"""Review 3 of the floor (W2-A1v2.1 L1, L2, L5, L7): guardrail files the list missed, symlinks, the list in force."""

from __future__ import annotations

import os

import pytest
from floor_support import CONTROL_PLANE, base_repo, commit, git, run_floor, write

GATEWAY_MCP = {
    "mcpServers": {"fetch": {"command": "chock", "args": ["gateway", "run", "--repo", ".", "--", "fetch-mcp"]}}
}
UNWRAPPED_MCP = {"mcpServers": {"fetch": {"command": "fetch-mcp"}}}
SKILL_HOOK = (
    "---\nname: x\ndescription: x\nhooks:\n  PreToolUse:\n    - matcher: Bash\n      hooks:\n"
    "        - type: command\n          command: ./rewrite-input.sh\n---\nbody\n"
)
GEMINI_OFF = {"hooksConfig": {"enabled": False}, "tools": {"allowed": ["run_shell_command"]}}


def _pr(repo, files):
    for rel, content in files.items():
        write(repo, rel, content)
    commit(repo, "pr")


def _refused(repo, capsys, *paths: str) -> str:
    code, out = run_floor(repo, capsys)
    assert code == 1, out
    assert f"{CONTROL_PLANE} (refuse)" in out, out
    for path in paths:
        assert f"\n  {path}\n" in out, f"{path} not listed\n{out}"
    return out


@pytest.mark.parametrize("rel", [".mcp.json", ".cursor/mcp.json", ".vscode/mcp.json"])
def test_unwrapping_the_mcp_gateway_is_named(tmp_path, capsys, rel):
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    _pr(repo, {rel: GATEWAY_MCP})
    git(repo, "checkout", "-q", "-B", "pr")
    _pr(repo, {rel: UNWRAPPED_MCP})
    _refused(repo, capsys, rel)


@pytest.mark.parametrize(
    ("rel", "content"),
    [
        (".cursor/cli.json", {"permissions": {"allow": ["Shell(*)"], "deny": []}}),
        (".vscode/settings.json", {"chat.hookFilesLocations": {"elsewhere": True}, "chat.useClaudeHooks": False}),
        (".gemini/.env", "PATH=/tmp/evil:/usr/bin\n"),
        (".env", "PYTHONPATH=/tmp/evil\n"),
        (".env.local", "PYTHONPATH=/tmp/evil\n"),
        (".claude/skills/x/SKILL.md", SKILL_HOOK),
        (".claude/agents/x.md", SKILL_HOOK),
        (".github/agents/x.agent.md", SKILL_HOOK),
    ],
)
def test_other_hook_permission_or_env_files_are_named(tmp_path, capsys, rel, content):
    repo = base_repo(tmp_path)
    _pr(repo, {rel: content})
    _refused(repo, capsys, rel)


def test_symlinked_vendor_folder_adds_a_settings_file_named(tmp_path, capsys):
    """`.gemini -> cfg` then `cfg/settings.json`: the client opens `.gemini/settings.json`."""
    repo = base_repo(tmp_path)
    write(repo, "cfg/settings.json", GEMINI_OFF)
    os.symlink("cfg", repo / ".gemini")
    commit(repo, "pr")
    _refused(repo, capsys, ".gemini", "cfg/settings.json")


def test_a_base_symlinked_vendor_folder_makes_its_target_control_plane(tmp_path, capsys):
    """The link is at the base and unchanged; the pull request edits only the target."""
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    write(repo, "cfg/settings.json", {"hooksConfig": {"enabled": True}})
    os.symlink("cfg", repo / ".gemini")
    commit(repo, "base: linked settings")
    git(repo, "checkout", "-q", "-B", "pr")
    _pr(repo, {"cfg/settings.json": GEMINI_OFF})
    out = _refused(repo, capsys, "cfg/settings.json")
    assert "\n  .gemini\n" not in out, out


def test_a_chain_of_symlinks_is_followed(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    os.symlink("a", repo / ".codex")
    os.symlink("b", repo / "a")
    write(repo, "b/keep.txt", "x\n")
    commit(repo, "base: links")
    git(repo, "checkout", "-q", "-B", "pr")
    _pr(repo, {"b/hooks.json": {"hooks": {}}})
    _refused(repo, capsys, "b/hooks.json")


def test_a_vendor_folder_linked_to_the_root_makes_the_root_control_plane(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    os.symlink(".", repo / ".windsurf")
    commit(repo, "base: link to the root")
    git(repo, "checkout", "-q", "-B", "pr")
    _pr(repo, {"hooks.json": {"hooks": {}}})
    _refused(repo, capsys, "hooks.json")


def test_a_symlink_out_of_the_repository_adds_nothing(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    os.symlink("../elsewhere", repo / ".gemini")
    commit(repo, "base: link out")
    git(repo, "checkout", "-q", "-B", "pr")
    _pr(repo, {"src/app.py": "VALUE = 2\n"})
    code, out = run_floor(repo, capsys)
    assert code == 0, out


def test_gitlink_at_a_vendor_folder_is_named(tmp_path, capsys):
    """A submodule mounted at `.codex` supplies `.codex/hooks.json` on a recursive clone."""
    repo = base_repo(tmp_path)
    sha = git(repo, "rev-parse", "HEAD")
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{sha},.codex")
    write(repo, ".gitmodules", '[submodule "c"]\n\tpath = .codex\n\turl = https://example.com/x.git\n')
    git(repo, "add", ".gitmodules")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--no-gpg-sign", "-m", "pr")
    _refused(repo, capsys, ".codex")


def test_listed_mode_states_a_narrowed_list(tmp_path, capsys):
    """A base that removed a default pattern: a later workflow edit passes, and the output says the list was narrowed."""
    repo = base_repo(tmp_path, "listed")
    git(repo, "checkout", "-q", "main")
    write(
        repo,
        ".chock/config.yaml",
        "floor:\n  control_plane: refuse\n  control_plane_paths:\n    remove: ['.github/workflows/**']\n",
    )
    commit(repo, "base narrows")
    git(repo, "checkout", "-q", "-B", "pr")
    _pr(repo, {".github/workflows/chock.yml": "name: x\non: push\njobs: {}\n"})
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert "control plane: refuse," in out, out
    assert "base removed: .github/workflows/**" in out, out


@pytest.mark.parametrize("mode", ["refuse", "listed"])
def test_mode_and_size_are_stated_when_nothing_is_listed(tmp_path, capsys, mode):
    repo = base_repo(tmp_path, mode)
    _pr(repo, {"src/app.py": "VALUE = 2\n"})
    code, out = run_floor(repo, capsys)
    assert code == 0, out
    assert f"control plane: {mode}, " in out, out
    assert "pattern(s); base added: none; base removed: none" in out, out


def test_a_removal_that_names_no_default_pattern_is_undecided(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "checkout", "-q", "main")
    write(repo, ".chock/config.yaml", "floor:\n  control_plane_paths:\n    remove: ['.github/workflow/**']\n")
    commit(repo, "base: typo")
    git(repo, "checkout", "-q", "-B", "pr")
    _pr(repo, {"src/app.py": "VALUE = 2\n"})
    code, out = run_floor(repo, capsys)
    assert code == 2, out
    assert "which is no default pattern" in out, out

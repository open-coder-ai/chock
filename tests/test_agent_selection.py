"""--agents parsing: comma and space forms both work, and mistakes stop the run.

Regression for a live incident: `init --agents claude,cursor,grok <path>` swallowed the
path into the agent list (nargs="*"), silently filtered every unknown entry to nothing,
and the deselect pass then deleted the pristine wrappers of the repo the positional
defaulted to -- the current directory.
"""

from __future__ import annotations

import pytest

from chock.scaffold.init import cmd_init
from chock.toggles import recompile_main


def test_comma_separated_agents(tmp_path):
    repo = tmp_path / "repo"
    cmd_init([str(repo), "--skip-hooks", "--agents", "claude,cursor"])
    assert (repo / ".claude" / "CLAUDE.md").exists()
    assert (repo / ".cursorrules").exists()
    assert not (repo / ".gemini").exists()


def test_space_separated_agents(tmp_path):
    repo = tmp_path / "repo"
    cmd_init([str(repo), "--skip-hooks", "--agents", "claude", "cursor"])
    assert (repo / ".cursorrules").exists()
    assert not (repo / ".gemini").exists()


def test_unknown_agent_stops_before_any_write(tmp_path, capsys):
    repo = tmp_path / "repo"
    with pytest.raises(SystemExit):
        cmd_init([str(repo), "--skip-hooks", "--agents", "claude,cursro"])
    err = capsys.readouterr().err
    assert "cursro" in err
    assert "valid:" in err
    assert not repo.exists(), "a rejected selection must not scaffold anything"


def test_swallowed_repo_path_cannot_retarget_cwd(tmp_path, monkeypatch, capsys):
    # The incident shape: a path after --agents is eaten by nargs="*", the positional
    # falls back to ".". The run must die on the unknown "agent", not init the CWD
    # with an empty selection.
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    target = tmp_path / "target"
    with pytest.raises(SystemExit):
        cmd_init(["--skip-hooks", "--agents", "claude,cursor", str(target)])
    capsys.readouterr()
    assert not (cwd / ".chock").exists(), "the CWD repo must stay untouched"
    assert not target.exists()


def test_empty_agents_flag_errors(tmp_path, capsys):
    with pytest.raises(SystemExit):
        cmd_init([str(tmp_path / "repo"), "--skip-hooks", "--agents"])
    assert "at least one agent" in capsys.readouterr().err


def test_sync_rejects_unknown_agents(tmp_path, capsys):
    repo = tmp_path / "repo"
    cmd_init([str(repo), "--skip-hooks"])
    capsys.readouterr()
    with pytest.raises(SystemExit):
        recompile_main(["--repo", str(repo), "--agents", "claude,nope"])
    assert "nope" in capsys.readouterr().err


def test_duplicate_agents_are_deduped(tmp_path):
    # `--agents claude claude,cursor` is two agents, not three -- a duplicate once
    # wrote the wrapper twice and persisted twice into supported_agents.
    from chock.compile.surfaces import parse_agent_selection

    assert parse_agent_selection(["claude", "claude,cursor", "cursor"]) == ["claude", "cursor"]


def test_compile_rejects_unknown_agents(capsys):
    # `chock compile` is the third --agents consumer; it used to treat "claude,cursro"
    # as one agent name and write a silent `unsupported` coverage row for it.
    from chock.compile.compiler import main as compile_main

    with pytest.raises(SystemExit):
        compile_main(["some-policy", "--agents", "claude,cursro"])
    err = capsys.readouterr().err
    assert "cursro" in err
    assert "valid:" in err


def test_compile_defaults_to_configured_agents(tmp_path, monkeypatch):
    # A repo pinned to a subset must not have a bare `compile` rewrite coverage for all
    # thirteen agents -- that put the repo into drift `sync --check` then failed. Goes
    # through the CLI so the --repo-based config resolution itself is what is pinned.
    from chock.compile import compiler as compiler_mod

    (tmp_path / ".chock").mkdir()
    (tmp_path / ".chock" / "config.yaml").write_text("chock:\n  supported_agents: [claude, gemini]\n", encoding="utf-8")
    (tmp_path / ".agents" / "policies" / "p").mkdir(parents=True)

    seen: dict[str, object] = {}

    def fake_compile_policy(policy_dir, targets=None, output_root=None, agents=None, repo_root=None):
        seen["agents"] = agents
        return compiler_mod.CompileResult(policy_id="p", artifacts={}, coverage={"p": {}})

    monkeypatch.setattr(compiler_mod, "compile_policy", fake_compile_policy)
    assert compiler_mod.main(["p", "--repo", str(tmp_path)]) == 0
    assert seen["agents"] == ["claude", "gemini"]


def test_config_typo_is_as_loud_as_a_flag_typo(tmp_path, capsys):
    # The config path used to bypass validation entirely: supported_agents [claud]
    # compiled `unsupported` coverage and skipped the wrapper with a clean exit.
    (tmp_path / ".chock").mkdir()
    (tmp_path / ".chock" / "config.yaml").write_text("chock:\n  supported_agents: [claud]\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        recompile_main(["--repo", str(tmp_path), "--check"])
    err = capsys.readouterr().err
    assert "claud" in err
    assert "valid:" in err


def test_skill_references_use_cli_agent_vocabulary():
    # The chock-init skill names agents a caller feeds straight to --agents; a spelling
    # the CLI rejects turns the skill's documented flow into a loud failure. Walk the
    # WHOLE skill tree, not just references/*.md -- the rename first missed evals/suite.yaml
    # and interface.yaml, which live in sibling dirs a references-only glob never reached.
    from pathlib import Path

    from chock.scaffold.adapters import AGENT_FILES

    framework_root = Path(__file__).resolve().parents[1]
    skill_roots = (
        framework_root / ".agents" / "skills" / "chock-init",
        framework_root / "src" / "chock" / "packs" / "_skills" / "chock-init",
    )
    for root in skill_roots:
        for f in [*root.rglob("*.md"), *root.rglob("*.yaml")]:
            text = f.read_text(encoding="utf-8")
            assert "github_copilot" not in text, f"{f}: the --agents name is 'copilot', not 'github_copilot'"
            # a bare "kimi" that is not the "kimi-code" key is the pre-rename spelling
            assert "kimi," not in text and "kimi." not in text, f"{f}: the --agents name is 'kimi-code', not 'kimi'"
        table = (root / "references" / "adapters.md").read_text(encoding="utf-8")
        assert "kimi-code" in table, f"{root}: the --agents name is 'kimi-code'"
        assert "kimi-code" in AGENT_FILES and "copilot" in AGENT_FILES


def test_config_duplicate_agents_are_deduped(tmp_path):
    # The config path shares the whole selection contract, not half: a duplicated
    # supported_agents entry once compiled the wrapper twice and re-persisted itself.
    from chock.config import agents_from_config

    (tmp_path / ".chock").mkdir()
    (tmp_path / ".chock" / "config.yaml").write_text(
        "chock:\n  supported_agents: [claude, claude, cursor]\n", encoding="utf-8"
    )
    assert agents_from_config(tmp_path) == ["claude", "cursor"]

"""Directory-scoped guardrails next to vendored content in adopter repos."""

from __future__ import annotations

import shutil
from pathlib import Path

from conftest import baseline_policy

from chock.lock import compute_pack_hash
from chock.scaffold.init import cmd_init

GUARDRAILS = (
    ".agents/policies/AGENTS.md",
    ".agents/policies/CLAUDE.md",
    ".agents/skills/AGENTS.md",
    ".agents/skills/CLAUDE.md",
)


def test_init_writes_the_guardrail_pairs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    cmd_init([str(repo), "--skip-hooks"])
    for rel in GUARDRAILS:
        assert (repo / rel).exists(), rel
    for area in (".agents/policies", ".agents/skills"):
        agents_md = (repo / area / "AGENTS.md").read_bytes()
        claude_md = (repo / area / "CLAUDE.md").read_bytes()
        assert agents_md == claude_md
        assert not (repo / area / "CLAUDE.md").is_symlink()


def test_guardrails_state_the_right_contract(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    cmd_init([str(repo), "--skip-hooks"])
    policies = (repo / ".agents/policies/AGENTS.md").read_text(encoding="utf-8")
    assert "chock.lock" in policies and "verify" in policies, "policies guardrail must explain the pinning"
    skills = (repo / ".agents/skills/AGENTS.md").read_text(encoding="utf-8")
    assert ".claude/skills" in skills and "bridge" in skills, "skills guardrail must warn about the bridge copy"


def test_edited_guardrail_is_preserved_on_rerun(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    cmd_init([str(repo), "--skip-hooks"])
    target = repo / ".agents/policies/AGENTS.md"
    target.write_text("my own vendoring rules\n", encoding="utf-8")
    cmd_init([str(repo), "--skip-hooks"])
    assert target.read_text(encoding="utf-8") == "my own vendoring rules\n"
    assert ".agents/policies/AGENTS.md" in capsys.readouterr().out, "the skip must be reported, not silent"


def test_guardrails_never_enter_a_policy_pack(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    cmd_init([str(repo), "--skip-hooks"])
    src = baseline_policy("protect-main-branch")
    dest = repo / ".agents" / "policies" / "protect-main-branch"
    shutil.copytree(src, dest)
    assert compute_pack_hash(dest) == compute_pack_hash(src)
    for skill_dir in (repo / ".agents" / "skills").iterdir():
        if skill_dir.is_dir():
            assert not (skill_dir / "AGENTS.md").exists(), f"guardrail leaked into {skill_dir.name}"
            assert not (skill_dir / "CLAUDE.md").exists(), f"guardrail leaked into {skill_dir.name}"

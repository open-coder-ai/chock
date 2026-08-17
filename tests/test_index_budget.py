"""F2 attention-budget tests for INDEX.md."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from chock.index.cli import cmd_refresh


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".chock").mkdir()
    return repo


def _rule(root: Path, policy_id: str, enforcement: str = "advise", text: str = "x") -> None:
    dir_ = root / ".agents" / "policies" / policy_id
    dir_.mkdir(parents=True)
    (dir_ / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "id": policy_id,
                "artifact": "rule",
                "enforcement": enforcement,
                "rule": {"text": text},
                "provenance": {"license": "Apache-2.0", "trust_tier": "sandbox"},
            }
        ),
        encoding="utf-8",
    )


def test_under_budget_no_extended_file(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "AGENTS.md").write_text("# repo\n\n## Rules\n", encoding="utf-8")
    _rule(repo, "p1", "advise", "one")

    assert cmd_refresh(["--repo", str(repo)]) == 0
    assert (repo / ".agents" / "policies" / "INDEX.md").exists()
    assert not (repo / ".agents" / "policies" / "INDEX-extended.md").exists()


def test_over_budget_demotes_advise_only_keeps_pointer(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "AGENTS.md").write_text("# repo\n\n## Rules\n", encoding="utf-8")
    _rule(repo, "zzz-block", "block", "block rule")
    _rule(repo, "aaa-advise", "advise", "a" * 4000)

    (repo / ".chock" / "config.yaml").write_text(
        yaml.safe_dump({"chock": {"index": {"max_tokens": 50}}}),
        encoding="utf-8",
    )
    assert cmd_refresh(["--repo", str(repo)]) == 0

    main = (repo / ".agents" / "policies" / "INDEX.md").read_text(encoding="utf-8")
    assert "zzz-block" in main
    assert "aaa-advise" not in main
    assert "INDEX-extended.md" in main

    extended = (repo / ".agents" / "policies" / "INDEX-extended.md").read_text(encoding="utf-8")
    assert "aaa-advise" in extended
    assert "block rule" not in extended


def test_eighty_percent_warning_fires(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "AGENTS.md").write_text("# repo\n\n## Rules\n", encoding="utf-8")
    _rule(repo, "p1", "block", "word " * 30)

    (repo / ".chock" / "config.yaml").write_text(
        yaml.safe_dump({"chock": {"index": {"max_tokens": 80}}}),
        encoding="utf-8",
    )

    assert cmd_refresh(["--repo", str(repo)]) == 0
    captured = capsys.readouterr()
    assert "% of budget" in captured.err


def test_no_config_file_default_2000(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "AGENTS.md").write_text("# repo\n\n## Rules\n", encoding="utf-8")
    _rule(repo, "p1", "advise", "rule text")

    assert not (repo / ".chock" / "config.yaml").exists()
    assert cmd_refresh(["--repo", str(repo)]) == 0
    captured = capsys.readouterr()
    assert "max 2000" in captured.out

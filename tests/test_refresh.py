"""`chock sync` CLI tests."""

from __future__ import annotations

from pathlib import Path

import yaml

from chock.index.cli import cmd_refresh


def _repo(tmp_path: Path) -> Path:
    return tmp_path / "repo"


def _init_policy(root: Path, policy_id: str) -> None:
    dir_ = root / ".agents" / "policies" / policy_id
    dir_.mkdir(parents=True)
    (dir_ / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "id": policy_id,
                "name": policy_id,
                "artifact": "rule",
                "enforcement": "advise",
                "rule": {"text": "rule text"},
                "provenance": {"author": "x", "license": "Apache-2.0", "trust_tier": "sandbox"},
            }
        ),
        encoding="utf-8",
    )


def test_refresh_is_idempotent(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _init_policy(repo, "p1")
    (repo / "AGENTS.md").write_text("# repo\n\n## Rules\n", encoding="utf-8")

    assert cmd_refresh(["--repo", str(repo)]) == 0
    first = (repo / ".agents" / "policies" / "INDEX.md").read_bytes()
    mtime = (repo / ".agents" / "policies" / "INDEX.md").stat().st_mtime

    assert cmd_refresh(["--repo", str(repo)]) == 0
    second = (repo / ".agents" / "policies" / "INDEX.md").read_bytes()
    assert first == second
    assert (repo / ".agents" / "policies" / "INDEX.md").stat().st_mtime == mtime


def test_check_exits_non_zero_on_stale_index_and_zero_on_fresh(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _init_policy(repo, "p1")
    (repo / "AGENTS.md").write_text("# repo\n\n## Rules\n", encoding="utf-8")

    assert cmd_refresh(["--repo", str(repo)]) == 0
    assert cmd_refresh(["--repo", str(repo), "--check"]) == 0

    (repo / ".agents" / "policies" / "INDEX.md").write_text("stale\n", encoding="utf-8")
    assert cmd_refresh(["--repo", str(repo), "--check"]) == 1


def test_check_never_writes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _init_policy(repo, "p1")
    (repo / "AGENTS.md").write_text("# repo\n\n## Rules\n", encoding="utf-8")

    cmd_refresh(["--repo", str(repo)])
    (repo / ".agents" / "policies" / "INDEX.md").write_text("stale\n", encoding="utf-8")
    mtime = (repo / ".agents" / "policies" / "INDEX.md").stat().st_mtime

    cmd_refresh(["--repo", str(repo), "--check"])

    assert (repo / ".agents" / "policies" / "INDEX.md").read_text() == "stale\n"
    # mtime should remain the manually-written value; --check must not rewrite it.
    assert (repo / ".agents" / "policies" / "INDEX.md").stat().st_mtime == mtime

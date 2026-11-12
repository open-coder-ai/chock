"""IR-F73: `sync` refreshes a committed gate.py in a repo with no gate policy, so `sync --check` passes."""

from __future__ import annotations

from pathlib import Path

from conftest import init_repo

from chock.scaffold.recompile import compiled_differences, recompile

OLD_RUNNER = "# a runner from an older engine\n"


def _policy_less_repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path)
    (repo / ".agents" / "policies").mkdir(parents=True)
    (repo / ".chock" / "bin").mkdir(parents=True)
    (repo / ".chock" / "config.yaml").write_text("chock:\n  supported_agents: [claude]\n", encoding="utf-8")
    return repo


def test_sync_refreshes_a_stale_runner_with_no_gate_policy(tmp_path: Path) -> None:
    repo = _policy_less_repo(tmp_path)
    recompile(repo, ["claude"])
    runner = repo / ".chock" / "bin" / "gate.py"
    runner.write_text(OLD_RUNNER, encoding="utf-8")
    assert "differs: bin/gate.py" in compiled_differences(repo, ["claude"])

    recompile(repo, ["claude"])

    assert runner.read_text(encoding="utf-8") != OLD_RUNNER
    assert compiled_differences(repo, ["claude"]) == []


def test_recompile_refreshes_every_stale_vendored_runtime_without_hook_install(tmp_path: Path) -> None:
    """`skip_hooks` (refresh after install) runs no vendor installer, so only the vendored refresh rewrites these."""
    repo = _policy_less_repo(tmp_path)
    recompile(repo, ["claude"])
    bin_dir = repo / ".chock" / "bin"
    stale = sorted(bin_dir.glob("*.py"))
    for path in stale:
        path.write_text(OLD_RUNNER, encoding="utf-8")
    assert len(stale) > 1

    recompile(repo, ["claude"], skip_hooks=True)

    assert [p.name for p in stale if p.read_text(encoding="utf-8") == OLD_RUNNER] == []
    assert compiled_differences(repo, ["claude"]) == []

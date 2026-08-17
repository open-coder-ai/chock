"""Tests for engine-scan: drop-in policy folders enforced without manual compile."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import yaml

from chock.hooks.autocompile import auto_compile
from chock.hooks.install import main as install_main


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    return repo


def _make_hook_policy(repo: Path, policy_id: str) -> Path:
    policy_dir = repo / ".agents" / "policies" / policy_id
    policy_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": policy_id,
        "name": f"Test {policy_id}",
        "version": "0.0.1",
        "description": "test hook",
        "artifact": "hook",
        "enforcement": "block",
        "hook": {
            "gate": {
                "kind": "forbidden_ref",
                "on": ["commit", "push"],
                "action": "block",
                "message": f"blocked by {policy_id}",
                "params": {"refs": ["main"]},
            }
        },
    }
    (policy_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return policy_dir


def _make_rule_policy(repo: Path, policy_id: str) -> Path:
    policy_dir = repo / ".agents" / "policies" / policy_id
    policy_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": policy_id,
        "name": f"Rule {policy_id}",
        "version": "0.0.1",
        "description": "test rule",
        "artifact": "rule",
        "enforcement": "advise",
        "rule": {"text": "do the right thing"},
    }
    (policy_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return policy_dir


class TestAutoCompile:
    def test_drop_in_hook_policy_gets_compiled(self, tmp_path: Path) -> None:
        """A hook policy dropped in without prior compile is auto-compiled by install-hooks."""
        repo = _init_repo(tmp_path)
        _make_hook_policy(repo, "my-hook")

        auto_compile(repo)

        compiled_gate = repo / ".chock" / "compiled" / "my-hook" / "git-hook" / "gate.json"
        assert compiled_gate.exists(), "gate.json should be auto-compiled from drop-in"

    def test_already_compiled_policy_is_not_touched(self, tmp_path: Path) -> None:
        """An already-compiled policy must not be recompiled (incremental, not rebuild)."""
        repo = _init_repo(tmp_path)
        _make_hook_policy(repo, "my-hook")
        auto_compile(repo)

        gate_path = repo / ".chock" / "compiled" / "my-hook" / "git-hook" / "gate.json"
        mtime_before = gate_path.stat().st_mtime

        auto_compile(repo)

        mtime_after = gate_path.stat().st_mtime
        assert mtime_after == mtime_before, "Second auto-compile should not touch already-compiled gate.json"

    def test_rule_policy_not_compiled_as_hook(self, tmp_path: Path) -> None:
        """Rule policies are not artifact: hook so auto-compile must skip them."""
        repo = _init_repo(tmp_path)
        _make_rule_policy(repo, "my-rule")

        auto_compile(repo)

        compiled_hook = repo / ".chock" / "compiled" / "my-rule" / "git-hook"
        assert not compiled_hook.exists(), "Rule policies should not produce git-hook output"

    def test_malformed_policy_does_not_stop_the_others(self, tmp_path: Path) -> None:
        """A malformed folder is skipped AND the remaining policies still compile.

        Named 'aaa-broken' so it sorts first: if failure were not isolated per policy,
        it would abort the loop before 'zzz-good' was ever reached.
        """
        repo = _init_repo(tmp_path)
        bad_dir = repo / ".agents" / "policies" / "aaa-broken"
        bad_dir.mkdir(parents=True)
        (bad_dir / "manifest.yaml").write_text("id: aaa-broken\nartifact: hook\n  bad: [indent\n", encoding="utf-8")
        _make_hook_policy(repo, "zzz-good")

        auto_compile(repo)

        assert (repo / ".chock" / "compiled" / "zzz-good" / "git-hook").exists(), (
            "A malformed policy must not prevent later policies from compiling"
        )

    def test_compile_failure_does_not_stop_the_others(self, tmp_path: Path) -> None:
        """One policy failing to COMPILE must not disable enforcement for the rest.

        This is the enforcement hole a loop-level try/except creates: a third-party
        drop-in that fails to build would silently take the mandatory guards offline
        while `install-hooks` still exited 0.
        """
        repo = _init_repo(tmp_path)
        _make_hook_policy(repo, "aaa-first")
        _make_hook_policy(repo, "zzz-second")

        import chock.compile.compiler as compiler_mod

        real = compiler_mod.compile_policy

        def flaky(pack_dir, *args, **kwargs):
            if "aaa-first" in str(pack_dir):
                raise RuntimeError("simulated build failure")
            return real(pack_dir, *args, **kwargs)

        with mock.patch.object(compiler_mod, "compile_policy", flaky):
            auto_compile(repo)  # must not raise

        compiled = repo / ".chock" / "compiled"
        assert not (compiled / "aaa-first" / "git-hook").exists(), "failing policy should not be compiled"
        assert (compiled / "zzz-second" / "git-hook").exists(), (
            "a failing policy must not prevent later policies from compiling"
        )

    def test_ordering_is_stable(self, tmp_path: Path) -> None:
        """Compiled hooks are sorted by policy id, giving deterministic ordering."""
        repo = _init_repo(tmp_path)
        _make_hook_policy(repo, "zzz-policy")
        _make_hook_policy(repo, "aaa-policy")
        auto_compile(repo)

        from chock.hooks.install import _discover_policy_hooks

        scripts = _discover_policy_hooks(repo, "git-pre-commit.sh")
        ids = [s.parent.parent.name for s in scripts]
        assert ids == sorted(ids), f"Hooks must be sorted; got {ids}"


class TestInstallHooksDropIn:
    def test_install_hooks_enforces_drop_in_without_prior_compile(self, tmp_path: Path) -> None:
        """install-hooks auto-compiles a dropped-in policy so it appears in pre-commit.d."""
        repo = _init_repo(tmp_path)
        _make_hook_policy(repo, "my-hook")

        assert install_main([str(repo)]) == 0

        wrappers = list((repo / ".git" / "hooks" / "pre-commit.d").glob("50-chock-policy-*"))
        assert len(wrappers) >= 1, "Drop-in policy should be registered as a hook wrapper"

"""Recompile installed policies from config, refreshing compiled artifacts and hooks."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from chock.compile.compiler import _load_manifest, compile_policy
from chock.compile.levels import DISABLED
from chock.config import load_config, policy_status
from chock.emit import write_generated_json

# Used here and historically imported from here by callers; importing from this module
# keeps the import direction downward (their real homes are lower layers).
from chock.policies import discover_policy_dirs
from chock.vendored import vendored_differences


class BookkeepingError(RuntimeError):
    """Bookkeeping the attestation chain depends on failed after a successful compile.

    Raised only for the lockfile: the artifacts on disk are consistent (the compile
    succeeded and swapped atomically), but committing them against a stale lock breaks
    `verify` for everyone. CLI callers turn this into a non-zero exit with the message.
    """


def _compile_all(repo_root: Path, agents: list[str], compiled_root: Path) -> dict[str, dict[str, str]]:
    """Compile every enabled policy into `compiled_root`. Returns the coverage map.

    Parameterised by output root so `recompile` and `compiled_differences` share one
    implementation. A check that runs a second copy of the logic verifies the copy.
    """
    config = load_config(repo_root)
    coverage: dict[str, dict[str, str]] = {}

    for pack_dir in discover_policy_dirs(repo_root):
        manifest = _load_manifest(pack_dir)
        policy_id = manifest.get("id") or pack_dir.name
        status = policy_status(config, policy_id, manifest)

        if status["state"] == "disabled":
            coverage[policy_id] = {agent: DISABLED for agent in agents}
            continue

        result = compile_policy(
            pack_dir,
            targets=status["targets"],
            output_root=compiled_root,
            agents=agents,
            repo_root=repo_root,
        )
        if result.coverage.get(policy_id):
            coverage[policy_id] = result.coverage[policy_id]

    return coverage


def compiled_differences(repo_root: Path | str, agents: list[str]) -> list[str]:
    """Every way the committed compiled tree differs from what the manifests produce now.

    `.chock/compiled/` is generated but committed, because the compiled gate is what
    actually enforces -- reviewing a manifest diff without it reviews intent, not effect.
    That argument only holds if the two are guaranteed to match, and nothing guaranteed it:
    a manifest could declare one set of protected branches while the committed gate blocked
    another, and `validate`, `refresh --check` and `eval` all passed.

    `eval` cannot catch this either -- it builds its gate from the manifest, so it would
    vouch for a policy that is not the one installed.

    The vendored runtimes in `.chock/bin/` are checked too, by `vendored_differences`
    below. They are not compiled output -- they are verbatim copies of packaged sources --
    but they are what the compiled gates execute, so they belong to the same guarantee.
    """
    repo_root = Path(repo_root)
    actual_root = repo_root / ".chock" / "compiled"
    diffs: list[str] = []

    with tempfile.TemporaryDirectory(prefix="chock-compilecheck-") as tmp:
        expected_root = Path(tmp) / "compiled"
        expected_root.mkdir(parents=True)
        expected_coverage = _compile_all(repo_root, agents, expected_root)

        expected = {p.relative_to(expected_root) for p in expected_root.rglob("*") if p.is_file()}
        actual = (
            {p.relative_to(actual_root) for p in actual_root.rglob("*") if p.is_file()}
            if actual_root.exists()
            else set()
        )

        diffs += [f"missing: {rel.as_posix()}" for rel in sorted(expected - actual)]
        diffs += [f"stale: {rel.as_posix()}" for rel in sorted(actual - expected)]
        diffs += [
            f"differs: {rel.as_posix()}"
            for rel in sorted(expected & actual)
            if (expected_root / rel).read_bytes() != (actual_root / rel).read_bytes()
        ]

    diffs += vendored_differences(repo_root)

    # Coverage is compiled output too, and it is the file that states what is enforced.
    # An absent file and an empty one both claim nothing, so they compare equal: a repo with
    # no policies has no coverage.json and is not in drift for lacking one. A file that is
    # absent while policies *are* compiled still differs, because the expected map is not
    # empty then.
    coverage_path = repo_root / ".chock" / "coverage.json"
    committed = json.loads(coverage_path.read_text(encoding="utf-8")) if coverage_path.exists() else {}
    if committed != expected_coverage:
        diffs.append("differs: coverage.json")

    return diffs


def _refresh_bookkeeping(repo_root: Path) -> None:
    """Bring the index and the registry back in line with the policies on disk.

    Compiling is not the whole job. Now that the framework ships no policies, copying a
    folder in and running `recompile` is the ONLY way to install one -- and it left the
    registry and INDEX.md describing a repo that no longer existed. The installed validate
    hook then failed on every commit:

        [ERROR] registry_freshness: Registry is stale: hook 'protect-main-branch' not found.
        [WARN]  index_freshness: INDEX.md is stale. Run `chock sync`.

    So the documented install flow bricked the repo, which is the one failure this project
    treats as worse than no guard at all. `init` already does both of these; `recompile` is
    the command an adopter reaches for afterwards and must leave the repo just as usable.

    Failures are reported, never raised: a compile that succeeded must not be undone by
    bookkeeping that did not.
    """
    from chock.index.cli import cmd_refresh
    from chock.registry.core import save_registry, scan

    try:
        entries, _skips = scan(repo_root)
        save_registry(entries, repo_root)
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] registry scan failed: {exc}. Run `chock registry scan`.", file=sys.stderr)

    try:
        cmd_refresh(["--repo", str(repo_root)])
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] index refresh failed: {exc}. Run `chock sync`.", file=sys.stderr)

    # The lockfile too. `init` writes it, but `init` now installs nothing -- so a lock built
    # there is empty by definition, and without this it stays empty forever. `verify` then
    # reported "all packs match lockfile" over zero packs, passing even when an installed
    # policy had been edited: an integrity check that cannot fail.
    #
    # Unlike the registry and index above, a lock failure is NOT a warning. The compiled
    # artifacts just changed; a lockfile still attesting the previous ones makes every
    # subsequent `verify` -- this adopter's and every teammate's -- fail on a repo nobody
    # tampered with. A [WARN] plus exit 0 let exactly that get committed.
    try:
        from chock.lock import build_lock, write_lock

        write_lock(build_lock(repo_root), repo_root)
    except Exception as exc:  # noqa: BLE001
        raise BookkeepingError(
            f"chock.lock was not updated ({exc}). The compiled artifacts are in place, but the "
            "lockfile still attests the previous ones -- `chock check --only verify` will fail "
            "until a `chock sync --repo .` succeeds."
        ) from exc


def refresh_after_install(repo_root: Path) -> None:
    """Recompile so coverage reflects the settings.json an install just wrote.

    `install-hooks` used to edit coverage.json directly, which made it and `recompile`
    disagree about one file. Coverage is derived, so the way to raise a claim is to derive
    it again. A failure here leaves a stale claim, not a broken repo -- the hooks are
    installed either way -- so warn rather than fail an install that already succeeded.
    """
    try:
        from chock.config import agents_from_config

        # skip_hooks: the git hooks went in already; redoing them would only make the
        # ordering matter.
        recompile(repo_root, agents_from_config(repo_root), skip_hooks=True)
    except Exception as exc:  # noqa: BLE001 - never fail an install over bookkeeping
        print(f"[WARN] coverage not refreshed: {exc}. Run `chock sync --repo .`", file=sys.stderr)


def recompile(repo_root: Path | str, agents: list[str], skip_hooks: bool = False) -> dict[str, Any]:
    """Compile all enabled policies from a clean compiled/ directory and install hooks.

    Disabled policies are skipped, and their coverage is recorded as DISABLED.
    Stale compiled artifacts are removed by clearing .chock/compiled first.
    Leaves the repo consistent -- see `_refresh_bookkeeping`.
    Returns the written coverage dict.
    """
    repo_root = Path(repo_root)
    chock_dir = repo_root / ".chock"
    compiled_root = chock_dir / "compiled"
    coverage_path = chock_dir / "coverage.json"

    # Build into a staging tree and swap on success, so a mid-build failure never touches the
    # live one. Deleting compiled/ and zeroing coverage.json up front meant a single malformed
    # manifest -- raising partway through the loop -- left every OTHER policy's gate deleted,
    # coverage empty, and chock.lock pointing at artifacts that no longer existed: one typo
    # disabling enforcement repo-wide and stranding the lockfile. `compiled_differences` already
    # compiles into a temp dir this way. The temp lives inside .chock so the swap is a rename on
    # one filesystem, not a cross-device copy.
    chock_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="chock-recompile-", dir=chock_dir) as tmp:
        staged_chock = Path(tmp)
        staged_compiled = staged_chock / "compiled"
        staged_compiled.mkdir(parents=True)

        # vendor_runner writes <staged_chock>/bin/gate.py, derived from the output tree.
        coverage = _compile_all(repo_root, agents, staged_compiled)

        # The whole build succeeded: replace the live artifacts. Only now is the old tree gone.
        if compiled_root.exists():
            shutil.rmtree(compiled_root)
        shutil.move(str(staged_compiled), str(compiled_root))
        staged_runner = staged_chock / "bin" / "gate.py"
        if staged_runner.exists():
            (chock_dir / "bin").mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(staged_runner), str(chock_dir / "bin" / "gate.py"))

    write_generated_json(coverage_path, coverage)

    if not skip_hooks:
        from chock.hooks.installers import get_hooks_dir, install_policy_hooks

        install_policy_hooks(repo_root, get_hooks_dir(repo_root))

        # The SessionStart arm hook re-installs the git hooks above on a fresh clone
        # (git never clones them). Wiring, not a policy surface: no coverage claim, so
        # it may run after coverage was derived without making the two disagree.
        from chock.hooks.sessionstart_install import install_sessionstart_hook

        try:
            if install_sessionstart_hook(repo_root):
                print("Registered SessionStart arm hook in .claude/settings.json")
        except ValueError as exc:
            print(f"[WARN] {exc}", file=sys.stderr)

        # Agent-native guard wiring is part of `sync`, not a separate verb an adopter has
        # to discover. It was `install-hooks`-only, so the documented init+add+sync flow
        # left every PreToolUse fragment compiled but uninstalled -- coverage honestly said
        # `advisory`, while the docs said sync "rewires the repo". Installing must follow
        # the swap above (the installers read the fresh fragments), which is after coverage
        # was derived -- so when wiring actually changed, coverage is derived again from a
        # throwaway compile (emitted artifacts do not depend on install state; only the
        # coverage verdict does).
        from chock.hooks.agenthooks_install import install_agent_hooks, installed_agent_hooks_policy_ids
        from chock.hooks.cursor_install import install_cursor_hooks, installed_cursor_policy_ids
        from chock.hooks.pretooluse_install import install_pretooluse_hooks, installed_pretooluse_policy_ids

        def _witness() -> tuple[set[str], set[str], set[str]]:
            return (
                installed_pretooluse_policy_ids(repo_root),
                installed_cursor_policy_ids(repo_root),
                installed_agent_hooks_policy_ids(repo_root),
            )

        before = _witness()
        for label, installer in (
            ("PreToolUse hook(s) in .claude/settings.json", install_pretooluse_hooks),
            ("Cursor hook entr(y/ies) in .cursor/hooks.json", install_cursor_hooks),
            ("agent hook(s) in .github/hooks/chock.json", install_agent_hooks),
        ):
            try:
                installed = installer(repo_root)
            except ValueError as exc:
                print(f"[WARN] {exc}", file=sys.stderr)
            else:
                if installed:
                    print(f"Registered {len(installed)} {label}")
        if _witness() != before:
            with tempfile.TemporaryDirectory(prefix="chock-coverage-", dir=chock_dir) as tmp2:
                coverage = _compile_all(repo_root, agents, Path(tmp2) / "compiled")
            write_generated_json(coverage_path, coverage)

    # After the artifacts, never before: the index and registry describe what was compiled.
    # `compiled_differences` deliberately does NOT call this -- a --check that repairs what
    # it measures cannot fail a build twice.
    _refresh_bookkeeping(repo_root)

    return coverage

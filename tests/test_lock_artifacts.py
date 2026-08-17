"""The lockfile must attest the artifact that enforces, not only the one that is authored.

`chock.lock` hashed `.agents/policies/<id>` -- the source pack -- and nothing else.
What actually blocks a commit is `.chock/compiled/<id>`, and no command hashed it.
So deleting a compiled `gate.json`, or weakening its regex in place, disabled enforcement
while `verify` printed "all packs match lockfile".

That is the worst shape this failure can take. A missing control is a gap; a control that is
missing while the tool certifies it as present is a false attestation, and attestation is
what the lockfile exists to provide.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from chock.lock import build_lock, verify_lock, write_lock
from chock.scaffold.recompile import recompile

AGENTS = ["claude"]
POLICY_ID = "protect-main-branch"


@pytest.fixture
def locked_repo(tmp_path: Path) -> Path:
    """A repo with one compiled policy and a lockfile written from it."""
    from conftest import baseline_policy

    policy = tmp_path / ".agents" / "policies" / POLICY_ID
    policy.parent.mkdir(parents=True)
    shutil.copytree(baseline_policy(POLICY_ID), policy)
    recompile(tmp_path, AGENTS, skip_hooks=True)
    write_lock(build_lock(tmp_path), tmp_path)

    ok, failures = verify_lock(tmp_path)
    assert ok, failures
    return tmp_path


def _gate(repo: Path) -> Path:
    return repo / ".chock" / "compiled" / POLICY_ID / "git-hook" / "gate.json"


def test_the_lockfile_records_the_compiled_artifacts(locked_repo: Path) -> None:
    entry = json.loads((locked_repo / "chock.lock").read_text(encoding="utf-8"))["packs"][0]
    assert entry["artifacts_sha256"], "a compiled pack must pin what it compiled to"
    assert entry["artifacts_sha256"] != entry["sha256"], "source and artifact hashes must be distinct"


def test_a_weakened_compiled_gate_fails_verify(locked_repo: Path) -> None:
    """The exact reproduction: the gate still exists and no longer blocks anything."""
    spec = json.loads(_gate(locked_repo).read_text(encoding="utf-8"))
    spec["params"]["refs"] = []
    _gate(locked_repo).write_text(json.dumps(spec), encoding="utf-8")

    ok, failures = verify_lock(locked_repo)
    assert not ok and any("artifact" in f for f in failures), failures


def test_a_deleted_compiled_gate_fails_verify(locked_repo: Path) -> None:
    _gate(locked_repo).unlink()

    ok, failures = verify_lock(locked_repo)
    assert not ok and any("artifact" in f for f in failures), failures


def test_an_untouched_repo_still_verifies(locked_repo: Path) -> None:
    """The check must be satisfiable, or it gets switched off."""
    ok, failures = verify_lock(locked_repo)
    assert ok, failures


def test_a_lockfile_without_artifact_hashes_is_not_a_failure(locked_repo: Path) -> None:
    """Older lockfiles predate the field. Unpinned is not the same as mismatched."""
    lock_path = locked_repo / "chock.lock"
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    for entry in data["packs"]:
        entry.pop("artifacts_sha256", None)
    lock_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    ok, failures = verify_lock(locked_repo)
    assert ok, failures


def test_a_neutered_runner_fails_verify(locked_repo: Path) -> None:
    """`verify` is the attestation command, so it must judge the file that executes.

    The vendored runtimes are not hashed per pack -- they are shared -- so they were outside
    the lockfile entirely. That left `verify` printing "all packs match lockfile" against a
    runner whose `run()` had been replaced with `return 0`.
    """
    runner = locked_repo / ".chock" / "bin" / "gate.py"
    runner.write_text(runner.read_text(encoding="utf-8").replace("def run(", "def run_off(", 1), encoding="utf-8")

    ok, failures = verify_lock(locked_repo)
    assert not ok and any("vendored runtime" in f for f in failures), failures

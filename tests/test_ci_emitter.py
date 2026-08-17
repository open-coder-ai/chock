"""ci-gate emitter: must derive from the manifest and emit a step that can actually fail.

The old emitter's push step was `... || true` (never fails) and its commit step ran
`git diff --cached`, which a CI checkout never has staged -- both always passed. This checks
the replacement the opposite way: build a real repo with a real violation, extract the
step's own `run:` body, execute it, and read the exit code.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml
from conftest import WORKING_BASH as BASH
from conftest import baseline_policy, needs_bash

from chock.compile.compiler import compile_policy
from chock.compile.surfaces import Surface

SCAN_SECRETS_DIR = baseline_policy("scan-secrets")

# A broken bash (the Windows WSL relay with no distro) exits 1 for everything, which is
# indistinguishable from "the gate blocked" -- the block-side test below passed spuriously
# on such machines. conftest.working_bash() proves the interpreter before it is trusted.


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _compiled_step(repo_root: Path, policy_dir: Path) -> tuple[dict, Path]:
    # The step's `run:` body hardcodes the canonical `.chock/compiled/...` path (it has
    # to: that is where a real adopter's compiled tree lives), so the test tree must use it
    # too, or the emitted command would resolve against a directory that does not exist.
    out = repo_root / ".chock" / "compiled"
    compile_policy(policy_dir, targets=[Surface.CI_GATE.value], output_root=out, repo_root=repo_root)
    step_path = out / policy_dir.name / "ci-gate" / "step.yaml"
    steps = yaml.safe_load(step_path.read_text(encoding="utf-8"))
    return steps[0], step_path


def test_step_has_no_bypass_and_no_hardcoded_refs(tmp_path: Path) -> None:
    step, _ = _compiled_step(tmp_path, SCAN_SECRETS_DIR)
    body = step["run"]
    assert "|| true" not in body, "a step that cannot fail enforces nothing"
    assert "0000000" not in body, "hardcoded refs check nothing real"
    assert "--event ci" in body
    assert "GITHUB_BASE_REF" in body


def test_gate_json_is_written_alongside_the_step(tmp_path: Path) -> None:
    """ci-gate must carry its own resolved gate, not depend on git-hook's copy existing."""
    _, step_path = _compiled_step(tmp_path, SCAN_SECRETS_DIR)
    assert (step_path.parent / "gate.json").exists()


def test_push_only_gate_emits_nothing() -> None:
    """A gate scoped to `push` only has no CI meaning (see runner.py); emitting a step that
    can never fire would be exactly the old bug in a new shape.
    """
    import tempfile

    from chock.compile.emitters import ci as ci_emitter

    with tempfile.TemporaryDirectory() as tmp:
        policy_dir = Path(tmp) / "policy"
        policy_dir.mkdir()
        (policy_dir / "manifest.yaml").write_text(
            yaml.safe_dump(
                {
                    "id": "push-only",
                    "name": "Push only",
                    "version": "0.0.1",
                    "description": "d",
                    "artifact": "hook",
                    "enforcement": "block",
                    "hook": {
                        "gate": {
                            "kind": "forbidden_ref",
                            "on": ["push"],
                            "action": "block",
                            "message": "no",
                            "params": {"refs": ["main"]},
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        out = Path(tmp) / "out"
        out.mkdir()
        emitted = ci_emitter.emit(policy_dir, out, {"id": "push-only"})
        assert emitted == []


@needs_bash
def test_emitted_step_actually_fails_on_a_violation(tmp_path: Path) -> None:
    """The whole point: run the compiled step's own bash body against a repo with a real
    secret introduced on the PR branch, and observe a non-zero exit -- not assume one.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "trunk")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "secret.py").write_text('KEY = "AKIAIOSFODNN7EXAMPLE"\n', encoding="utf-8")  # pragma: allowlist secret
    _git(repo, "add", "secret.py")
    _git(repo, "commit", "-m", "add secret")
    # actions/checkout leaves a real `origin/<base>` remote-tracking ref behind; the step's
    # `origin/$GITHUB_BASE_REF` depends on that, so fake it rather than fetching from nothing.
    _git(repo, "update-ref", "refs/remotes/origin/trunk", "trunk")

    step, _ = _compiled_step(repo, SCAN_SECRETS_DIR)
    env = {**__import__("os").environ, "GITHUB_BASE_REF": "trunk", "GITHUB_HEAD_REF": "feature"}
    proc = subprocess.run([BASH, "-c", step["run"]], cwd=repo, capture_output=True, text=True, env=env)
    assert proc.returncode == 1, f"expected the gate to block, got {proc.returncode}: {proc.stdout}{proc.stderr}"


@needs_bash
def test_emitted_step_allows_a_clean_range(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "trunk")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "app.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "clean change")
    _git(repo, "update-ref", "refs/remotes/origin/trunk", "trunk")

    step, _ = _compiled_step(repo, SCAN_SECRETS_DIR)
    env = {**__import__("os").environ, "GITHUB_BASE_REF": "trunk", "GITHUB_HEAD_REF": "feature"}
    proc = subprocess.run([BASH, "-c", step["run"]], cwd=repo, capture_output=True, text=True, env=env)
    assert proc.returncode == 0, f"expected allow, got {proc.returncode}: {proc.stdout}{proc.stderr}"

"""`.chock/compiled/` is generated but committed, so it must be pinned to its source.

Committing it is deliberate: the compiled gate is what actually enforces, so reviewing a
manifest diff without it reviews intent rather than effect. That argument only holds if the
two are guaranteed to match -- and nothing guaranteed it. A manifest could declare one set
of protected branches while the committed gate blocked another, and `validate`,
`refresh --check`, `check-matrix` and `eval` all passed.

`eval` is the reason this matters most. It builds its gate from the manifest, so against a
stale compiled artifact it reports the policy as fully passing while the installed hook
enforces something else -- the eval suite actively vouching for a policy that is not the
one running.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from chock.scaffold.recompile import compiled_differences, recompile

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ["claude"]


def test_this_repo_has_compiled_what_it_declares() -> None:
    """The dogfooding claim for compiled output, checked rather than assumed.

    Agents come from the CLI's own resolver, not a second copy of the rule: reimplementing
    it here first produced a false failure, which is the same defect class this file exists
    to catch, one level up.
    """
    from chock.config import agents_from_config as _agents_from_config

    assert not compiled_differences(ROOT, _agents_from_config(ROOT)), "run `chock sync --repo .`"


@pytest.fixture
def compiled_repo(tmp_path: Path) -> Path:
    """A repo with one policy, compiled and in sync."""
    from conftest import baseline_policy

    policy = tmp_path / ".agents" / "policies" / "protect-main-branch"
    policy.parent.mkdir(parents=True)
    import shutil

    shutil.copytree(baseline_policy("protect-main-branch"), policy)
    recompile(tmp_path, AGENTS, skip_hooks=True)
    assert not compiled_differences(tmp_path, AGENTS)
    return tmp_path


def test_a_manifest_change_without_a_recompile_is_drift(compiled_repo: Path) -> None:
    """The defect exactly as found: the gate enforces refs the manifest no longer declares."""
    manifest = compiled_repo / ".agents" / "policies" / "protect-main-branch" / "manifest.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data["hook"]["gate"]["params"]["refs"] = ["main", "master", "release"]
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    drift = compiled_differences(compiled_repo, AGENTS)
    assert any("gate.json" in d for d in drift), drift


def test_a_hand_edited_compiled_artifact_is_drift(compiled_repo: Path) -> None:
    """The compiled tree is generated output; editing it directly must not survive review."""
    gate = compiled_repo / ".chock" / "compiled" / "protect-main-branch" / "git-hook" / "gate.json"
    spec = json.loads(gate.read_text(encoding="utf-8"))
    spec["params"]["refs"] = []
    gate.write_text(json.dumps(spec), encoding="utf-8")

    assert any(d.startswith("differs:") for d in compiled_differences(compiled_repo, AGENTS))


def test_a_deleted_artifact_is_drift(compiled_repo: Path) -> None:
    gate = compiled_repo / ".chock" / "compiled" / "protect-main-branch" / "git-hook" / "gate.json"
    gate.unlink()
    assert any(d.startswith("missing:") for d in compiled_differences(compiled_repo, AGENTS))


def test_an_artifact_for_a_removed_policy_is_drift(compiled_repo: Path) -> None:
    """A stale gate still compiles, still installs a hook, and still claims coverage."""
    orphan = compiled_repo / ".chock" / "compiled" / "retired-policy" / "git-hook"
    orphan.mkdir(parents=True)
    (orphan / "gate.json").write_text("{}", encoding="utf-8")

    assert any(d.startswith("stale:") for d in compiled_differences(compiled_repo, AGENTS))


def test_stale_coverage_is_drift(compiled_repo: Path) -> None:
    """coverage.json is compiled output too, and it is the file that states what is enforced."""
    coverage = compiled_repo / ".chock" / "coverage.json"
    coverage.write_text(json.dumps({"protect-main-branch": {"claude": "enforced"}}), encoding="utf-8")

    assert any("coverage.json" in d for d in compiled_differences(compiled_repo, AGENTS))


def test_check_writes_nothing(compiled_repo: Path) -> None:
    """A check that repairs what it measures cannot fail the build twice."""
    gate = compiled_repo / ".chock" / "compiled" / "protect-main-branch" / "git-hook" / "gate.json"
    gate.write_text("{}", encoding="utf-8")

    compiled_differences(compiled_repo, AGENTS)
    assert gate.read_text(encoding="utf-8") == "{}"


def test_a_neutered_vendored_runner_is_drift(compiled_repo: Path) -> None:
    """The cheapest bypass in the system, and nothing detected it.

    `.chock/bin/gate.py` is what every compiled gate executes. Replacing the body of
    `run()` with `return 0` disables every gate in the repo at once. Reproduced against a
    real adopter repo: a secret and a direct commit to `main` both went through while the
    installed pre-commit hook printed "[PASS] All checks passed", and `validate`, `verify`,
    `eval` and `recompile --check` each exited 0.
    """
    runner = compiled_repo / ".chock" / "bin" / "gate.py"
    assert runner.exists(), "compiling a gate must vendor the runner it calls"
    runner.write_text(runner.read_text(encoding="utf-8").replace("def run(", "def run_disabled(", 1), encoding="utf-8")

    assert any("bin/gate.py" in d for d in compiled_differences(compiled_repo, AGENTS))


def test_a_check_does_not_re_vendor_the_runner(compiled_repo: Path) -> None:
    """The check must not repair the one file it is now responsible for noticing.

    `vendor_runner` used to resolve its destination by walking up from the output directory
    and falling back to `git rev-parse` in the *current working directory*. Compiling into a
    temp tree took that fallback, so `recompile --check` silently rewrote the working repo's
    runner -- restoring a tampered copy and then reporting no difference.
    """
    runner = compiled_repo / ".chock" / "bin" / "gate.py"
    runner.write_text("tampered\n", encoding="utf-8")

    compiled_differences(compiled_repo, AGENTS)
    assert runner.read_text(encoding="utf-8") == "tampered\n"


def test_validate_reports_drift_the_adopter_would_otherwise_never_see(compiled_repo: Path) -> None:
    """`validate` is what the installed pre-commit hook runs, so it is where this must land.

    Before this, only `recompile --check` caught a tampered gate -- and that runs in CI, not
    on the adopter's machine at commit time.
    """
    from chock.validation.checks_drift import check_compiled_drift
    from chock.validation.report import Report

    gate = compiled_repo / ".chock" / "compiled" / "protect-main-branch" / "git-hook" / "gate.json"
    spec = json.loads(gate.read_text(encoding="utf-8"))
    spec["params"]["refs"] = []
    gate.write_text(json.dumps(spec), encoding="utf-8")

    report = Report()
    check_compiled_drift(compiled_repo, report)
    assert not report.is_clean(), "a weakened gate must fail validation"


def test_validate_does_not_fault_a_policy_that_was_never_compiled(tmp_path: Path) -> None:
    """ "Never compiled" is not "compiled and then changed".

    `new policy` scaffolds a folder and leaves compiling to the adopter. Reporting that as
    drift would fail the first commit of every onboarding.
    """
    import shutil

    from conftest import baseline_policy

    from chock.validation.checks_drift import check_compiled_drift
    from chock.validation.report import Report

    policy = tmp_path / ".agents" / "policies" / "protect-main-branch"
    policy.parent.mkdir(parents=True)
    shutil.copytree(baseline_policy("protect-main-branch"), policy)

    report = Report()
    check_compiled_drift(tmp_path, report)
    assert report.is_clean(), "an uncompiled policy is not drift"


def _git(root: Path, *args: str) -> None:
    import subprocess

    subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def drifted_git_repo(compiled_repo: Path) -> Path:
    """The compiled_repo under git, committed, then drifted by a hand-edit."""
    _git(compiled_repo, "init", "--quiet", ".")
    _git(compiled_repo, "config", "user.email", "a@b.c")
    _git(compiled_repo, "config", "user.name", "t")
    _git(compiled_repo, "add", "-A")
    _git(compiled_repo, "commit", "-q", "-m", "base")

    gate = compiled_repo / ".chock" / "compiled" / "protect-main-branch" / "git-hook" / "gate.json"
    spec = json.loads(gate.read_text(encoding="utf-8"))
    spec["params"]["refs"] = []
    gate.write_text(json.dumps(spec), encoding="utf-8")
    _git(compiled_repo, "add", "-A")
    _git(compiled_repo, "commit", "-q", "-m", "drift lands")
    return compiled_repo


def test_at_commit_time_unrelated_work_is_not_blocked_by_preexisting_drift(drifted_git_repo: Path) -> None:
    """Drift the staged diff never touched is drift this commit did not introduce.

    The common case is an engine upgrade changing what `recompile` emits: every commit in
    the repo then failed until someone repaired an artifact their diff never went near.
    Under `event="commit"` that drift is a warning naming the fix; plain `validate` -- what
    CI runs -- still fails on it.
    """
    from chock.validation.checks_drift import check_compiled_drift
    from chock.validation.report import Report

    (drifted_git_repo / "notes.md").write_text("unrelated\n", encoding="utf-8")
    _git(drifted_git_repo, "add", "notes.md")

    report = Report()
    check_compiled_drift(drifted_git_repo, report, event="commit")
    assert report.is_clean(), "unrelated staged work must not be blocked"
    assert report.warnings, "the drift must still be reported"
    assert "Pre-existing drift" in report.warnings[0].message

    strict = Report()
    check_compiled_drift(drifted_git_repo, strict)
    assert not strict.is_clean(), "outside commit the check stays strict"


def test_at_commit_time_touching_the_drifted_tree_still_blocks(drifted_git_repo: Path) -> None:
    """Scoping is by the staged diff, not a free pass: touch the policy, answer for it."""
    from chock.validation.checks_drift import check_compiled_drift
    from chock.validation.report import Report

    manifest = drifted_git_repo / ".agents" / "policies" / "protect-main-branch" / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n# touched\n", encoding="utf-8")
    _git(drifted_git_repo, "add", str(manifest))

    report = Report()
    check_compiled_drift(drifted_git_repo, report, event="commit")
    assert not report.is_clean(), "a commit touching policy source must answer for drift"

"""Packaged Agent Plugins output must not go stale in silence.

The drift class `test_compiled_freshness.py` closes, one layer up. Reproduced in a real
adopter repo before this check existed: copy a catalog policy in, edit its `description`,
run `recompile`, and then

    validate .                   exit=0  [PASS] All checks passed.
    recompile --repo . --check   exit=0  Compiled artifacts match their manifests.
    eval --repo .                exit=0
    plugin build --check         exit=1    differs: protect-main-branch/plugin.json

Four of the five said the repo was clean. Only the command nothing tells an adopter to run
noticed -- `init`, `new policy` and the `policy-init` skill all emit no packaged output, so
`plugin.json` is a file most adopters meet only because a copied catalog policy brought one.

Worse than compiled drift in one respect. A stale compiled artifact misleads the repo that
holds it; a stale `plugin.json` is read by clients we do not control and cannot correct.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from chock.compile.compiler import _load_manifest
from chock.plugin.build import build_plugin
from chock.validation.checks_drift import check_plugin_drift
from chock.validation.report import Report


def _report(root: Path, event: str | None = None) -> Report:
    report = Report()
    check_plugin_drift(root, report, event=event)
    return report


def _severities(report: Report) -> list[str]:
    findings = [*report.errors, *report.warnings, *report.infos]
    return [f.severity for f in findings if f.check == "plugin_drift"]


@pytest.fixture
def packaged_repo(tmp_path: Path) -> Path:
    """One policy, packaged as an Agent Plugin and in sync."""
    from conftest import baseline_policy

    policy = tmp_path / ".agents" / "policies" / "protect-main-branch"
    policy.parent.mkdir(parents=True)
    shutil.copytree(baseline_policy("protect-main-branch"), policy)
    # Whatever the catalog happened to commit is not the fixture's claim; build it here so
    # "in sync" is established by this test rather than inherited.
    shutil.rmtree(policy / "skills", ignore_errors=True)
    build_plugin(policy, _load_manifest(policy), tmp_path)
    assert _report(tmp_path).is_clean()
    return tmp_path


def _policy(root: Path) -> Path:
    return root / ".agents" / "policies" / "protect-main-branch"


def test_an_unpackaged_policy_is_not_judged(tmp_path: Path) -> None:
    """Opt-in by presence, and this is the half that matters most.

    Packaging deliberately is not a compile Surface, so a repo that never asked for Agent
    Plugins must never start failing because this check exists.
    """
    from conftest import baseline_policy

    policy = tmp_path / ".agents" / "policies" / "protect-main-branch"
    policy.parent.mkdir(parents=True)
    shutil.copytree(baseline_policy("protect-main-branch"), policy)
    shutil.rmtree(policy / "skills", ignore_errors=True)
    (policy / "plugin.json").unlink(missing_ok=True)

    assert _report(tmp_path).is_clean(), "a policy with no plugin.json is not packaged"


def test_the_original_reproduction_a_description_edit(packaged_repo: Path) -> None:
    """The exact change that four checks called clean."""
    manifest_path = _policy(packaged_repo) / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["description"] = "Prevent direct commits and pushes to the default branch."
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    report = _report(packaged_repo)
    assert not report.is_clean(), "an edited manifest must not leave plugin.json vouching for the old one"


def test_a_deleted_skill_is_drift(packaged_repo: Path) -> None:
    """`plugin.json` is the label; SKILL.md is the only part carrying the policy's text.

    A package that keeps its metadata and loses its capability still installs, and reads to
    a client as a policy with nothing to say.
    """
    (_policy(packaged_repo) / "skills" / "protect-main-branch" / "SKILL.md").unlink()

    assert not _report(packaged_repo).is_clean()


def test_a_hand_edited_plugin_json_is_drift(packaged_repo: Path) -> None:
    plugin = _policy(packaged_repo) / "plugin.json"
    data = json.loads(plugin.read_text(encoding="utf-8"))
    data["description"] = "something the manifest never said"
    plugin.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    assert not _report(packaged_repo).is_clean()


def test_rebuilding_clears_it(packaged_repo: Path) -> None:
    """The remedy the finding names has to be the remedy that works."""
    manifest_path = _policy(packaged_repo) / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["description"] = "Prevent direct commits and pushes to the default branch."
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    assert not _report(packaged_repo).is_clean()

    build_plugin(_policy(packaged_repo), _load_manifest(_policy(packaged_repo)), packaged_repo)

    assert _report(packaged_repo).is_clean()


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def drifted_git_repo(packaged_repo: Path) -> Path:
    _git(packaged_repo, "init", "--quiet", ".")
    _git(packaged_repo, "config", "user.email", "a@b.c")
    _git(packaged_repo, "config", "user.name", "t")
    _git(packaged_repo, "add", "-A")
    _git(packaged_repo, "commit", "-q", "-m", "base")

    plugin = _policy(packaged_repo) / "plugin.json"
    data = json.loads(plugin.read_text(encoding="utf-8"))
    data["description"] = "stale"
    plugin.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    _git(packaged_repo, "add", "-A")
    _git(packaged_repo, "commit", "-q", "-m", "drift lands")
    return packaged_repo


def test_at_commit_time_unrelated_work_is_not_blocked(drifted_git_repo: Path) -> None:
    """Same judgement as compiled drift, and it must stay the same judgement.

    A gate that fires on whoever commits next, rather than on whoever caused the drift, is
    how gates get disabled.
    """
    (drifted_git_repo / "notes.md").write_text("unrelated\n", encoding="utf-8")
    _git(drifted_git_repo, "add", "notes.md")

    assert _severities(_report(drifted_git_repo, event="commit")) == ["warning"]


def test_at_commit_time_touching_the_packaged_policy_still_blocks(drifted_git_repo: Path) -> None:
    """Scoping is by the staged diff, not a free pass: touch the policy, answer for it.

    Staging an unchanged path stages nothing, so the edit is what makes this a real
    reproduction rather than a `git add` that quietly no-ops.
    """
    manifest = _policy(drifted_git_repo) / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n# touched\n", encoding="utf-8")
    _git(drifted_git_repo, "add", str(manifest))

    assert _severities(_report(drifted_git_repo, event="commit")) == ["error"]


def test_plain_validate_stays_strict(drifted_git_repo: Path) -> None:
    """Without `--event commit` there is no staged diff to scope by, and CI should fail."""
    assert _severities(_report(drifted_git_repo)) == ["error"]

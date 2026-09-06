"""`chock eval export --format context-report` -- the run/v0.1 export."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from conftest import FRAMEWORK_ROOT, baseline_policy

from chock.compile.emitters.advisory import advisory_lines
from chock.eval import context_report as cr
from chock.eval.cli import main
from chock.manifest import load_manifest


def _repo(tmp_path: Path, policy_id: str) -> Path:
    """A repo containing one shipped baseline policy, copied so the test owns the tree."""
    dest = tmp_path / ".agents" / "policies" / policy_id
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(baseline_policy(policy_id), dest)
    return tmp_path


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Never commit secrets to the repository.", "never-commit-secrets-to-the-repository"),
        ("!!! --- ???", "rule"),
        (
            "abcdefgh abcdefgh abcdefgh abcdefgh abcdefgh abcdefgh abcdefgh",
            "abcdefgh-abcdefgh-abcdefgh-abcdefgh-abcdefgh-abc",
        ),
    ],
)
def test_slug_examples(text: str, expected: str) -> None:
    assert cr.slug(text) == expected


def test_path_slug_replaces_unsafe_characters() -> None:
    assert cr.path_slug("tc-001: force push?") == "tc-001-force-push"


def test_export_layout_on_a_fixture_policy(tmp_path: Path) -> None:
    """`git-safety` has tier-3 cases; the export writes one subject file and one dir per case."""
    repo = _repo(tmp_path, "git-safety")
    out = tmp_path / "out"

    result = cr.export(repo, out, ["git-safety"])

    assert result.exported == ["git-safety"]
    assert not result.skipped
    assert not result.errors

    subject = out / "subjects" / "git-safety.md"
    assert subject.is_file()

    policy_dir = repo / ".agents" / "policies" / "git-safety"
    suite = yaml.safe_load((policy_dir / "evals" / "suite.yaml").read_text(encoding="utf-8"))["suite"]
    case_ids = [c["id"] for c in suite["cases"] if "execute" not in c]
    assert case_ids, "fixture policy must actually have tier-3 cases"

    for case_id in case_ids:
        case_dir = out / "evals" / f"git-safety--{case_id}"
        assert (case_dir / "prompt.md").is_file()
        assert (case_dir / "graders" / "expect.md").is_file()

    run_manifest = (out / "run.json").read_text(encoding="utf-8")
    assert '"contextReportRun": "v0.1"' in run_manifest
    assert '"id": "git-safety"' in run_manifest
    assert '"models": []' in run_manifest
    assert (out / "README.md").is_file()


def test_prompt_and_grader_tags_share_the_rendered_rule_id(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "git-safety")
    out = tmp_path / "out"
    cr.export(repo, out, ["git-safety"])

    prompt = yaml.safe_load(
        (out / "evals" / "git-safety--tc-001" / "prompt.md").read_text(encoding="utf-8").split("---")[1]
    )
    grader = yaml.safe_load(
        (out / "evals" / "git-safety--tc-001" / "graders" / "expect.md").read_text(encoding="utf-8").split("---")[1]
    )
    rule_tag = next(t.split(":", 1)[1] for t in prompt["tags"] if t.startswith("rule:"))
    assert rule_tag == grader["rule"]
    # Pinned against a verified `context-report run --dry-run` of this export (see the PR body):
    # context-report's own extractor strips underscores before deriving the id.
    assert rule_tag == "never-withoutapproval-forcepush-resethard-branch"


def test_subject_text_equals_chocks_own_renderer_output(tmp_path: Path) -> None:
    """The subject file must carry exactly what `advisory_lines` renders -- no re-derivation."""
    repo = _repo(tmp_path, "git-safety")
    out = tmp_path / "out"
    cr.export(repo, out, ["git-safety"])

    policy_dir = repo / ".agents" / "policies" / "git-safety"
    manifest, _ = load_manifest(policy_dir)
    expected_lines = advisory_lines(policy_dir, manifest, repo)

    written = (out / "subjects" / "git-safety.md").read_text(encoding="utf-8")
    assert written == cr.render_subject("git-safety", expected_lines)
    assert "\n".join(expected_lines) in written


def test_no_tier3_cases_is_a_skip_not_a_silent_zero(tmp_path: Path) -> None:
    """A policy where every case is deterministic gets a one-line notice, not silence."""
    repo = _repo(tmp_path, "block-no-verify")
    out = tmp_path / "out"

    result = cr.export(repo, out, ["block-no-verify"])

    assert result.exported == []
    assert not result.errors
    assert len(result.skipped) == 1
    assert "block-no-verify" in result.skipped[0]
    assert "no tier-3 cases" in result.skipped[0]
    assert not out.exists()


def test_older_suite_shape_raises_a_distinct_error(tmp_path: Path) -> None:
    """`eval_suite:`/`test_cases:` (pre-`suite:`) has no `execute` concept -- must not read as zero."""
    repo = _repo(tmp_path, "minimal-content")
    out = tmp_path / "out"

    result = cr.export(repo, out, ["minimal-content"])

    assert result.exported == []
    assert not result.skipped
    assert len(result.errors) == 1
    assert "minimal-content" in result.errors[0]
    assert "no top-level `suite:` key" in result.errors[0]

    policy_dir = repo / ".agents" / "policies" / "minimal-content"
    from chock.eval.suites import discover_policies

    policy = discover_policies(repo, "minimal-content")[0]
    assert policy.dir == policy_dir
    with pytest.raises(cr.SuiteShapeError):
        cr.tier3_cases(policy)


def test_export_skips_skills_even_when_named_directly(tmp_path: Path) -> None:
    """This exporter is policies only; `discover_policies` also returns `.agents/skills/*`."""
    repo = _repo(tmp_path, "git-safety")
    skill_dir = repo / ".agents" / "skills" / "eval"
    skill_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FRAMEWORK_ROOT / ".agents" / "skills" / "eval", skill_dir)

    result = cr.export(repo, tmp_path / "out", ["eval"])

    assert result.exported == []
    assert any("eval" in e and "not found" in e for e in result.errors)


def test_unknown_policy_id_is_reported_not_dropped(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "git-safety")
    result = cr.export(repo, tmp_path / "out", ["no-such-policy"])
    assert result.exported == []
    assert any("no-such-policy" in e for e in result.errors)


def test_cli_export_writes_the_directory_and_exits_zero(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "git-safety")
    out = tmp_path / "out"

    rc = main(["export", "--format", "context-report", "--out", str(out), "--repo", str(repo), "git-safety"])

    assert rc == 0
    assert (out / "subjects" / "git-safety.md").is_file()
    assert (out / "run.json").is_file()


def test_cli_export_exits_nonzero_on_a_suite_shape_error(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "minimal-content")
    out = tmp_path / "out"

    rc = main(["export", "--format", "context-report", "--out", str(out), "--repo", str(repo), "minimal-content"])

    assert rc == 2


def test_cli_still_runs_evals_when_the_first_token_is_not_export(tmp_path: Path) -> None:
    """`export` is special-cased; every other `chock eval [policy_id]` invocation is untouched."""
    repo = _repo(tmp_path, "git-safety")

    assert main(["git-safety", "--repo", str(repo)]) == 0

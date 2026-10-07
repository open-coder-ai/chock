"""release.yml: the one PyPI publisher refuses a tag != v<version> or a commit off main."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
RELEASE = WORKFLOWS / "release.yml"
GUARD_STEP = "Refuse unless the tag is v<version> and the commit is on main"
PUBLISH_ACTION = "pypa/gh-action-pypi-publish"
SHA_PIN = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
JOB_PERMISSIONS = {
    "guard": {"contents": "read"},
    "pypi": {"id-token": "write", "attestations": "write", "contents": "read"},
    "binaries": {"contents": "read"},
    "release": {"contents": "write"},
}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _jobs() -> dict:
    return _load(RELEASE)["jobs"]


def _step_names(job: dict) -> list[str]:
    return [s.get("name") or s.get("uses", "") for s in job["steps"]]


def test_triggers_only_on_v_tags() -> None:
    workflow = _load(RELEASE)
    assert (workflow.get(True) or workflow.get("on")) == {"push": {"tags": ["v*"]}}


def test_permissions_are_least_privilege_per_job() -> None:
    assert _load(RELEASE)["permissions"] == {}
    assert {name: job.get("permissions") for name, job in _jobs().items()} == JOB_PERMISSIONS
    assert _jobs()["pypi"]["environment"] == "pypi"


def test_pypi_uses_trusted_publishing_and_provenance() -> None:
    assert "secrets." not in RELEASE.read_text(encoding="utf-8")
    steps = _jobs()["pypi"]["steps"]
    publish = next(s for s in steps if s.get("uses", "").startswith(PUBLISH_ACTION))
    assert not {"password", "user"} & set(publish.get("with", {}))
    assert any(s.get("uses", "").startswith("actions/attest-build-provenance@") for s in steps)


@pytest.mark.parametrize("path", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_every_action_is_pinned_by_full_sha(path: Path) -> None:
    uses = [s["uses"] for job in _load(path)["jobs"].values() for s in job.get("steps", []) if "uses" in s]
    unpinned = [u for u in uses if not SHA_PIN.match(u)]
    assert not unpinned, f"{path.name}: actions not pinned by 40-hex SHA: {unpinned}"


def test_only_release_yml_publishes_to_pypi() -> None:
    """Two workflows on the same tag would publish twice; PyPI trusts only release.yml."""
    publishers = sorted(p.name for p in WORKFLOWS.glob("*.yml") if PUBLISH_ACTION in p.read_text(encoding="utf-8"))
    assert publishers == ["release.yml"]


def test_every_job_waits_for_the_guard() -> None:
    jobs = _jobs()
    assert jobs["pypi"]["needs"] == "guard"
    assert jobs["binaries"]["needs"] == "guard"
    assert set(jobs["release"]["needs"]) <= {"pypi", "binaries"}


def test_guard_checkout_sees_main() -> None:
    checkout = _jobs()["guard"]["steps"][0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"] == {"fetch-depth": 0, "persist-credentials": False}
    assert GUARD_STEP in _step_names(_jobs()["guard"])


def test_built_files_are_checked_before_attest_and_publish() -> None:
    names = _step_names(_jobs()["pypi"])
    check = names.index("Refuse unless dist holds exactly this version's sdist and wheel")
    assert names.index("Build sdist and wheel") < check < names.index("Attest build provenance")
    assert check < names.index("Publish to PyPI")


def _git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args]
    return subprocess.run(cmd, cwd=repo, env=env, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def clone(tmp_path: Path) -> tuple[Path, str, str]:
    """A clone whose origin/main holds one commit, plus a commit that is not on main."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "pyproject.toml").write_text('[project]\nname = "chock"\nversion = "1.2.3"\n', encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "on main")
    on_main = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", on_main)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "off main")
    off_main = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", on_main)
    return repo, on_main, off_main


def _run_guard(repo: Path, ref_name: str, sha: str) -> subprocess.CompletedProcess[str]:
    script = next(s["run"] for s in _jobs()["guard"]["steps"] if s.get("name") == GUARD_STEP)
    env = {**os.environ, "GITHUB_REF_NAME": ref_name, "GITHUB_SHA": sha}
    return subprocess.run(["bash", "-e", "-c", script], cwd=repo, env=env, capture_output=True, text=True, check=False)


needs_bash = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None or shutil.which("python3") is None,
    reason="guard step runs on ubuntu: bash and python3",
)


@needs_bash
def test_guard_accepts_matching_tag_on_main(clone: tuple[Path, str, str]) -> None:
    repo, on_main, _ = clone
    result = _run_guard(repo, "v1.2.3", on_main)
    assert result.returncode == 0, result.stdout + result.stderr


@needs_bash
@pytest.mark.parametrize("tag", ["v1.2.4", "1.2.3", "v1.2.3rc1", "v1.2", "vv1.2.3"])
def test_guard_refuses_tag_not_equal_to_version(clone: tuple[Path, str, str], tag: str) -> None:
    repo, on_main, _ = clone
    result = _run_guard(repo, tag, on_main)
    assert result.returncode != 0
    assert "is not v1.2.3" in result.stdout


@needs_bash
def test_guard_refuses_commit_not_on_main(clone: tuple[Path, str, str]) -> None:
    repo, _, off_main = clone
    result = _run_guard(repo, "v1.2.3", off_main)
    assert result.returncode != 0
    assert "is not on main" in result.stdout

"""publish.yml: tag-only PyPI trusted publishing that refuses a tag != v<version> or off main."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PUBLISH = WORKFLOWS / "publish.yml"
GUARD_STEP = "Refuse unless the tag is v<version> and the commit is on main"
PUBLISH_ACTION = "pypa/gh-action-pypi-publish"
SHA_PIN = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _job() -> dict:
    jobs = _load(PUBLISH)["jobs"]
    assert len(jobs) == 1, f"publish.yml must have one job, has {sorted(jobs)}"
    return next(iter(jobs.values()))


def _step_names(job: dict) -> list[str]:
    return [s.get("name") or s.get("uses", "") for s in job["steps"]]


def test_triggers_only_on_v_tags() -> None:
    triggers = _load(PUBLISH).get(True) or _load(PUBLISH).get("on")
    assert triggers == {"push": {"tags": ["v*"]}}


def test_permissions_are_least_privilege() -> None:
    assert _load(PUBLISH)["permissions"] == {}
    job = _job()
    assert job["permissions"] == {"id-token": "write", "contents": "read"}
    assert job["environment"] == "pypi"


def test_no_token_is_used() -> None:
    text = PUBLISH.read_text(encoding="utf-8")
    assert "secrets." not in text
    publish = next(s for s in _job()["steps"] if s.get("uses", "").startswith(PUBLISH_ACTION))
    assert not {"password", "user"} & set(publish.get("with", {}))


def test_every_action_is_pinned_by_full_sha() -> None:
    uses = [s["uses"] for s in _job()["steps"] if "uses" in s]
    assert any(u.startswith(PUBLISH_ACTION) for u in uses)
    unpinned = [u for u in uses if not SHA_PIN.match(u)]
    assert not unpinned, f"actions not pinned by 40-hex SHA: {unpinned}"


def test_guard_runs_before_build_and_publish() -> None:
    names = _step_names(_job())
    guard = names.index(GUARD_STEP)
    build = names.index("Build sdist and wheel")
    publish = names.index("Publish to PyPI")
    assert guard < build < publish


def test_checkout_sees_main_for_the_ancestry_check() -> None:
    checkout = next(s for s in _job()["steps"] if s.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["persist-credentials"] is False


def test_only_publish_yml_publishes_to_pypi() -> None:
    """Two workflows on the same tag would publish twice; PyPI trusts only publish.yml."""
    publishers = sorted(p.name for p in WORKFLOWS.glob("*.yml") if PUBLISH_ACTION in p.read_text(encoding="utf-8"))
    assert publishers == ["publish.yml"]


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
    script = next(s["run"] for s in _job()["steps"] if s.get("name") == GUARD_STEP)
    env = {**os.environ, "GITHUB_REF_NAME": ref_name, "GITHUB_SHA": sha}
    return subprocess.run(["bash", "-e", "-c", script], cwd=repo, env=env, capture_output=True, text=True, check=False)


needs_gnu_bash = pytest.mark.skipif(
    sys.platform != "linux" or shutil.which("bash") is None, reason="guard step runs on ubuntu (GNU grep -P)"
)


@needs_gnu_bash
def test_guard_accepts_matching_tag_on_main(clone: tuple[Path, str, str]) -> None:
    repo, on_main, _ = clone
    result = _run_guard(repo, "v1.2.3", on_main)
    assert result.returncode == 0, result.stdout + result.stderr


@needs_gnu_bash
@pytest.mark.parametrize("tag", ["v1.2.4", "1.2.3", "v1.2.3rc1", "v1.2", "vv1.2.3"])
def test_guard_refuses_tag_not_equal_to_version(clone: tuple[Path, str, str], tag: str) -> None:
    repo, on_main, _ = clone
    result = _run_guard(repo, tag, on_main)
    assert result.returncode != 0
    assert "is not v1.2.3" in result.stdout


@needs_gnu_bash
def test_guard_refuses_commit_not_on_main(clone: tuple[Path, str, str]) -> None:
    repo, _, off_main = clone
    result = _run_guard(repo, "v1.2.3", off_main)
    assert result.returncode != 0
    assert "is not on main" in result.stdout

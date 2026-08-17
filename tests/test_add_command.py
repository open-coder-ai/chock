"""`chock add` is the step that turns a scaffolded repo into a governed one.

The framework ships no policies, so before this existed adopting one meant cloning a
catalog, copying a folder, recompiling, and installing hooks -- four operations, one of
which is easy to forget, as the documented flow proved by leaving repos unable to commit.

Transport is `git clone --depth 1`, which inherits the adopter's existing credentials, so a
private catalog works with no token handling here. These tests use a local path, which is
the same code path minus the clone.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from chock.scaffold.add import add, locate

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


@pytest.fixture
def catalog(tmp_path: Path) -> Path:
    """A catalog in the published layout: base/ for policies, skills/ for skills."""
    root = tmp_path / "catalog"
    (root / "base").mkdir(parents=True)
    (root / "skills").mkdir(parents=True)
    shutil.copytree(
        FRAMEWORK_ROOT / ".agents" / "policies" / "protect-main-branch", root / "base" / "protect-main-branch"
    )
    skill = root / "skills" / "demo-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: demo-skill\ndescription: demo\n---\n\nbody\n", encoding="utf-8")
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / ".agents" / "policies").mkdir(parents=True)
    (r / ".agents" / "skills").mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", "."], cwd=r, check=True, capture_output=True)
    return r


def test_a_policy_lands_in_the_policies_tree(catalog: Path, repo: Path) -> None:
    dest = add(repo, "protect-main-branch", str(catalog), None, force=False).path
    assert dest == repo / ".agents" / "policies" / "protect-main-branch"
    assert (dest / "manifest.yaml").exists()


def test_a_skill_lands_in_the_skills_tree(catalog: Path, repo: Path) -> None:
    """The source directory decides the destination, so the adopter never has to say."""
    dest = add(repo, "demo-skill", str(catalog), None, force=False).path
    assert dest == repo / ".agents" / "skills" / "demo-skill"


def test_an_unknown_id_is_refused(catalog: Path, repo: Path) -> None:
    with pytest.raises(FileNotFoundError):
        add(repo, "no-such-thing", str(catalog), None, force=False)


def test_an_installed_artifact_is_never_silently_replaced(catalog: Path, repo: Path) -> None:
    """Once installed, the content is the adopter's -- that is why it is not bundled.

    Overwriting on a re-add would recreate exactly the loss the split exists to prevent.
    """
    dest = add(repo, "protect-main-branch", str(catalog), None, force=False).path
    manifest = dest / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n# our edit\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        add(repo, "protect-main-branch", str(catalog), None, force=False)
    assert "our edit" in manifest.read_text(encoding="utf-8")


def test_force_replaces_when_asked(catalog: Path, repo: Path) -> None:
    """Refusing is the default, not a ban."""
    dest = add(repo, "protect-main-branch", str(catalog), None, force=False).path
    (dest / "manifest.yaml").write_text("clobbered\n", encoding="utf-8")

    add(repo, "protect-main-branch", str(catalog), None, force=True)
    assert (dest / "manifest.yaml").read_text(encoding="utf-8") != "clobbered\n"


def test_a_missing_catalog_fails_loudly(repo: Path, tmp_path: Path) -> None:
    """A bad URL must not look like a missing artifact."""
    with pytest.raises(RuntimeError):
        add(repo, "anything", "https://example.invalid/no-such-catalog.git", None, force=False)


def test_locate_prefers_the_declared_areas(catalog: Path) -> None:
    src, area = locate(catalog, "protect-main-branch")
    assert src == catalog / "base" / "protect-main-branch"
    assert area == Path(".agents") / "policies"


def test_a_wrong_verify_sha_installs_nothing(repo: Path, catalog: Path) -> None:
    """A catalog policy carries guard scripts that run on every commit.

    So the hash is checked while the content is still in the temp clone. Verifying after the
    copy would mean an unexpected script had already been written into a repo whose next
    commit executes it.
    """
    from chock.scaffold.add import IntegrityError

    with pytest.raises(IntegrityError):
        add(repo, "protect-main-branch", str(catalog), None, force=False, verify_sha="not-the-hash")

    assert not (repo / ".agents" / "policies" / "protect-main-branch").exists(), "refusal must write nothing"


def test_the_reported_hash_is_the_one_that_verifies(repo: Path, catalog: Path) -> None:
    """The printed hash has to be usable as the next install's --verify-sha, or it is decoration."""
    first = add(repo, "protect-main-branch", str(catalog), None, force=False)

    second = tmp_repo = repo.parent / "second"
    tmp_repo.mkdir()
    again = add(second, "protect-main-branch", str(catalog), None, force=False, verify_sha=first.sha256)
    assert again.sha256 == first.sha256


def test_a_local_catalog_reports_no_commit(repo: Path, catalog: Path) -> None:
    """A directory has no commit to resolve, and inventing one would be a false provenance."""
    added = add(repo, "protect-main-branch", str(catalog), None, force=False)
    assert added.commit is None


def test_a_cloned_catalog_records_the_commit_it_resolved_to(repo: Path, catalog: Path) -> None:
    """`--ref main` means "whatever main pointed at then", so the answer must be recorded.

    Cloned over file:// rather than a local path, because a path short-circuits the clone --
    and the clone is the code path that has provenance to capture.
    """
    for args in (
        ["git", "init", "--quiet", "-b", "main", "."],
        ["git", "config", "user.email", "c@example.invalid"],
        ["git", "config", "user.name", "Catalog"],
        ["git", "add", "-A"],
        ["git", "commit", "--quiet", "-m", "catalog"],
    ):
        subprocess.run(args, cwd=catalog, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=catalog, check=True, capture_output=True, text=True
    ).stdout.strip()

    added = add(repo, "protect-main-branch", f"file://{catalog}", None, force=False)
    assert added.commit == head


def test_provenance_survives_the_lockfile_rebuild(repo: Path, catalog: Path) -> None:
    """`recompile` rebuilds the lockfile from disk, which knows the bytes but not the origin.

    Without recording it afterwards, "which catalog, at which commit" became unanswerable as
    soon as the terminal scrolled.
    """
    import json

    from chock.lock import build_lock, write_lock
    from chock.scaffold.add import record_provenance

    added = add(repo, "protect-main-branch", str(catalog), "v1", force=False)
    write_lock(build_lock(repo), repo)
    record_provenance(repo, "protect-main-branch", str(catalog), "v1", added)

    entry = next(p for p in json.loads((repo / "chock.lock").read_text())["packs"] if p["id"] == "protect-main-branch")
    assert entry["source"] == str(catalog)
    assert entry["source_ref"] == "v1"

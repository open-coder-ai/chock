"""`chock remove` deletes a folder from someone else's repository.

That is the whole reason this file exists. Every other command writes or reports; this one
destroys, and it had no tests at all. The cases below are the ones where getting it wrong
costs an adopter real work: removing the wrong policy, removing a mandatory one, removing
one whose manifest nobody could read, and leaving the compiled tree describing something
that is gone.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from chock.scaffold import remove

POLICY = {
    "id": "removable-policy",
    "name": "Removable Policy",
    "version": "0.0.1",
    "description": "A policy an adopter may remove.",
    "artifact": "rule",
    "enforcement": "advise",
    "rule": {"text": "never(commit): secrets"},
}


@pytest.fixture
def repo(tmp_path: Path, monkeypatch):
    """An adopter repo with policies on disk, and resync stubbed out.

    `remove` ends by calling sync, which recompiles the whole repo. Stubbing it keeps these
    tests about deletion, and records that the resync was requested -- because a removal that
    skipped it would leave the compiled tree, hooks and lockfile describing a policy that no
    longer exists.
    """
    calls: list[list[str]] = []
    monkeypatch.setattr("chock.lifecycle.sync_main", lambda argv: calls.append(list(argv)) or 0)

    def _make(manifest: dict | None, folder: str, raw: str | None = None) -> Path:
        pack = tmp_path / ".agents" / "policies" / folder
        pack.mkdir(parents=True, exist_ok=True)
        text = raw if raw is not None else yaml.safe_dump(manifest)
        (pack / "manifest.yaml").write_text(text, encoding="utf-8")
        return pack

    return tmp_path, _make, calls


def test_removes_the_policy_and_resyncs(repo, capsys) -> None:
    root, make, calls = repo
    pack = make(POLICY, "removable-policy")

    assert remove.main(["removable-policy", "--repo", str(root)]) == 0
    assert not pack.exists()
    assert calls == [["--repo", str(root)]], "the compiled tree must stop describing it"
    assert "Removed" in capsys.readouterr().out


def test_unknown_policy_deletes_nothing(repo, capsys) -> None:
    root, make, calls = repo
    pack = make(POLICY, "removable-policy")

    assert remove.main(["not-installed", "--repo", str(root)]) == 2
    assert pack.exists(), "a typo must not delete the policy that happens to be there"
    assert calls == []
    assert "Unknown policy" in capsys.readouterr().err


def test_mandatory_policy_is_refused(repo, capsys) -> None:
    root, make, calls = repo
    mandatory = dict(POLICY, id="required-policy", mandatory=True)
    pack = make(mandatory, "required-policy")

    assert remove.main(["required-policy", "--repo", str(root)]) == 2
    assert pack.exists()
    assert calls == []
    assert "mandatory" in capsys.readouterr().err


def test_an_unreadable_manifest_is_refused_not_assumed_optional(repo, capsys) -> None:
    """`_load_manifest` reports a parse failure and returns {}, which reads as "not mandatory".

    Acting on that would delete a mandatory policy on the strength of a file nobody could
    parse. When the tool cannot tell, refusing is the honest answer -- this is deletion in
    someone else's repository.
    """
    root, make, calls = repo
    pack = make(None, "broken-policy", raw="id: [unclosed")

    assert remove.main(["broken-policy", "--repo", str(root)]) == 2
    assert pack.exists()
    assert calls == []
    assert "could not be read" in capsys.readouterr().err


def test_matches_by_folder_name_when_the_id_differs(repo) -> None:
    """Adopters rename folders; the id in the manifest stays. Both must resolve."""
    root, make, calls = repo
    pack = make(dict(POLICY, id="canonical-id"), "renamed-folder")

    assert remove.main(["renamed-folder", "--repo", str(root)]) == 0
    assert not pack.exists()


def test_removes_only_the_named_policy(repo) -> None:
    root, make, calls = repo
    doomed = make(POLICY, "removable-policy")
    survivor = make(dict(POLICY, id="other-policy"), "other-policy")

    assert remove.main(["removable-policy", "--repo", str(root)]) == 0
    assert not doomed.exists()
    assert survivor.exists(), "removal is surgical, not a sweep"

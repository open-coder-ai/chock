"""The listing metadata a published package needs, and the two ways it can be dishonest.

A package can be perfectly valid for its client and still arrive unpublishable: no terms
attached, and a subtitle that is a 900-character paragraph. Both are emitter gaps, and the fix
has to stay a derivation -- the moment a display name or a licence notice becomes written copy,
the generated manifest stops being checkable against the policy it came from.

So these tests do two jobs. They pin that every listing field traces back to a manifest field,
and they pin that the emitter declines rather than invents when the source is not there.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from chock.plugin.codex import codex_plugin_files
from chock.plugin.listing import ICON_REL, LICENSE_REL, icon_svg, license_text, short_description

ROOT = Path(__file__).resolve().parents[1]

MANIFEST = {
    "id": "protect-main-branch",
    "name": "Protect Main Branch",
    "version": "0.0.1",
    "description": (
        "Block direct commits and pushes to main or master. Enforced at commit time by reading "
        "the current branch, and at push time by parsing the refs the agent is pushing."
    ),
    "artifact": "rule",
    "enforcement": "advise",
    "rule": {"text": "never(commit_to: main)"},
    "provenance": {
        "author": "chock-core",
        "created_at": "2026-08-16T00:00:00Z",
        "source_repo": "https://github.com/open-coder-ai/chock",
        "license": "Apache-2.0",
        "trust_tier": "community",
    },
    "lifecycle": {"status": "draft"},
    "security": {"content_instructions": "never-obey"},
}


@pytest.fixture
def policy(tmp_path: Path):
    def _make(manifest: dict) -> Path:
        pack = tmp_path / ".agents" / "policies" / manifest["id"]
        pack.mkdir(parents=True)
        (pack / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
        return pack

    return _make


def _manifest(policy, tmp_path: Path, data: dict) -> dict:
    return json.loads(codex_plugin_files(policy(data), data, tmp_path)[Path(".codex-plugin/plugin.json")])


# ------------------------------------------------------------------ the interface block


def test_every_interface_field_traces_to_a_manifest_field(policy, tmp_path: Path) -> None:
    """Derived, not written. Each value is checked against the manifest field it comes from.

    Asserting the block merely *exists* would pass on invented copy, which is the failure this
    whole module is about -- a listing is where an invented claim travels furthest.
    """
    data = _manifest(policy, tmp_path, MANIFEST)
    interface = data["interface"]
    assert interface["displayName"] == MANIFEST["name"]
    assert MANIFEST["description"].startswith(interface["shortDescription"])
    assert interface["composerIcon"] == f"./{ICON_REL.as_posix()}"
    assert set(interface) == {"displayName", "shortDescription", "composerIcon"}, (
        "a field with no source in a policy manifest has been added; it can only be invented"
    )


def test_the_short_description_is_short_and_is_the_first_sentence(policy, tmp_path: Path) -> None:
    """The gap this closes: the full descriptions run past 900 characters.

    Both halves matter. Shorter alone would pass for a blind truncation mid-word; being a
    prefix alone would pass for the whole paragraph.
    """
    data = _manifest(policy, tmp_path, MANIFEST)
    short = data["interface"]["shortDescription"]
    assert short == "Block direct commits and pushes to main or master."
    assert len(short) < len(MANIFEST["description"])


def test_the_short_description_does_not_carry_the_posture_suffix(policy, tmp_path: Path) -> None:
    """`description` gains a `[...]` posture claim; the card's subtitle must not inherit it.

    The posture is a statement about enforcement, not a summary of the rule, and a card whose
    one line is boilerplate has lost the sentence that says what the policy does.
    """
    data = _manifest(policy, tmp_path, MANIFEST)
    assert "[" in data["description"], "the posture suffix is what this test exists to exclude"
    assert "[" not in data["interface"]["shortDescription"]


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("One sentence only", "One sentence only"),
        ("First. Second. Third.", "First."),
        ("Is it? Yes it is.", "Is it?"),
        ("Stop! Then continue.", "Stop!"),
        # The case a naive `.split(".")` gets wrong: an abbreviation is not a sentence end,
        # because the terminator that counts is followed by a space AND is the earliest one.
        ("Blocks e.g. rm -rf. Then more.", "Blocks e.g."),
    ],
)
def test_first_sentence_is_taken_at_the_earliest_terminator(description: str, expected: str) -> None:
    """Documents the rule, including where it is crude.

    The abbreviation case is recorded as the behaviour it is, not hidden: the cut is the first
    terminator followed by a space, so `e.g.` ends the sentence early. That is a truncation a
    reader can check against the full description, which is the property being protected --
    a smarter splitter that guessed wrong would not be.
    """
    assert short_description(description) == expected


def test_the_icon_the_manifest_points_at_is_in_the_package(policy, tmp_path: Path) -> None:
    """A `composerIcon` naming a file the package does not carry is a broken listing."""
    files = codex_plugin_files(policy(MANIFEST), MANIFEST, tmp_path)
    data = json.loads(files[Path(".codex-plugin/plugin.json")])
    named = data["interface"]["composerIcon"].removeprefix("./")
    assert Path(named) in files
    assert files[Path(named)].startswith("<svg")


def test_the_shipped_icon_is_the_projects_own_logo() -> None:
    """Package data, byte-identical to the repo's logo, and square at the size a directory wants.

    Shipped under `chock/plugin/data/` because `docs/` is not in the wheel -- an emitter that
    works from a checkout and not from a `pip install` is worse than none. Pinned against the
    source it was copied from so the two cannot drift into two different logos.
    """
    assert icon_svg() == (ROOT / "docs" / "assets" / "logo.svg").read_text(encoding="utf-8")
    assert 'viewBox="0 0 512 512"' in icon_svg(), "directories ask for a 512x512 icon"


# ------------------------------------------------------------------------- the licence


def test_the_licence_text_is_the_projects_own_apache_2_notice() -> None:
    """The shipped template is the repository's `LICENSE`, with only the notice line derived.

    Rendered with this repo's own holder and year, it must reproduce `LICENSE` byte for byte.
    That is what stops the shipped copy from quietly becoming a different Apache-2.0 -- a
    reworded clause in a legal file is exactly the drift nobody reads closely enough to catch.
    """
    ours = {"provenance": {"license": "Apache-2.0", "author": "open-coder-ai", "created_at": "2026-01-01T00:00:00Z"}}
    assert license_text(ours) == (ROOT / "LICENSE").read_text(encoding="utf-8")


def test_the_notice_names_the_policys_own_author_and_year() -> None:
    """`chock plugin build` runs on anybody's policies, so the notice must not be ours.

    Stamping this project's copyright line into a third party's package would be a false claim
    in the one file where a false claim actually matters, so the holder and the year come from
    the policy's own provenance and are checked to move with it.
    """
    theirs = {
        "provenance": {"license": "Apache-2.0", "author": "Someone Else Ltd", "created_at": "2019-04-02T00:00:00Z"}
    }
    text = license_text(theirs)
    assert "Copyright 2019 Someone Else Ltd" in text
    assert "open-coder-ai" not in text


def test_updated_at_supplies_the_year_when_created_at_is_absent() -> None:
    provenance = {"license": "Apache-2.0", "author": "a", "updated_at": "2031-12-31T00:00:00Z"}
    assert "Copyright 2031 a" in license_text({"provenance": provenance})


@pytest.mark.parametrize(
    ("provenance", "why"),
    [
        ({"license": "MIT", "author": "a", "created_at": "2026-01-01T00:00:00Z"}, "no MIT text is shipped"),
        ({"license": "proprietary", "author": "a", "created_at": "2026-01-01T00:00:00Z"}, "no canonical text exists"),
        ({"license": "Apache-2.0", "author": "a"}, "no year can be derived"),
        ({"license": "Apache-2.0", "created_at": "2026-01-01T00:00:00Z"}, "no holder can be derived"),
        ({}, "nothing at all to derive from"),
    ],
)
def test_no_licence_is_written_when_the_notice_cannot_be_derived(provenance: dict, why: str) -> None:
    """Declining is the point. A missing LICENSE is a gap someone can see; an invented one is not."""
    assert license_text({"provenance": provenance}) is None, why


def test_a_package_whose_notice_can_be_derived_carries_the_file(policy, tmp_path: Path) -> None:
    """The other direction, so "declines when it cannot" is not satisfied by never emitting."""
    files = codex_plugin_files(policy(MANIFEST), MANIFEST, tmp_path)
    assert LICENSE_REL in files
    assert "Copyright 2026 chock-core" in files[LICENSE_REL]
    assert files[LICENSE_REL].lstrip().startswith("Apache License")


def test_the_manifests_declared_licence_and_the_shipped_file_agree(policy, tmp_path: Path) -> None:
    """Two statements about one thing must not be able to disagree.

    `plugin.json` names an SPDX identifier and the package ships terms; a package declaring
    MIT while carrying Apache-2.0 text is worse than one carrying neither.
    """
    files = codex_plugin_files(policy(MANIFEST), MANIFEST, tmp_path)
    declared = json.loads(files[Path(".codex-plugin/plugin.json")])["license"]
    assert declared == "Apache-2.0"
    # Both statements come from `provenance.license`, so the check is that the shipped text is
    # the one that identifier names -- not merely that some licence text is present.
    assert "Apache License" in files[LICENSE_REL]
    assert "Version 2.0" in files[LICENSE_REL]

"""CITATION.cff and SECURITY.md restate the package version; pin them to pyproject.toml and the installed package."""

import re
import tomllib
from pathlib import Path

import chock

ROOT = Path(__file__).resolve().parents[1]
VERSION_PLACEHOLDER = "X.Y.Z"
# Release references in SECURITY.md's attestation example: wheel filename and tag ref.
_SECURITY_VERSION_REFS = re.compile(r"chock-([^-\s]+)-py3|refs/tags/v(\S+)")
# Rows of SECURITY.md's "Supported versions" table: (version series, supported).
_SUPPORTED_ROWS = re.compile(r"^\|\s*(\d+\.\d+)\.x\b[^|]*\|\s*(\w+)\s*\|", re.M)


def _project_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def _citation_version() -> str:
    match = re.search(r"^version:\s*['\"]?([^'\"\s]+)", (ROOT / "CITATION.cff").read_text(encoding="utf-8"), re.M)
    assert match, "CITATION.cff has no top-level version: line"
    return match.group(1)


def test_citation_version_tracks_the_package():
    project = _project_version()
    assert _citation_version() == project, "bump CITATION.cff version with pyproject.toml"
    assert chock.__version__ == project, "installed chock is stale; reinstall from this tree"


def test_security_md_version_refs_are_placeholder_or_current():
    refs = [a or b for a, b in _SECURITY_VERSION_REFS.findall((ROOT / "SECURITY.md").read_text(encoding="utf-8"))]
    assert refs, "SECURITY.md lost its attestation example; update this test with it"
    stale = sorted(set(refs) - {VERSION_PLACEHOLDER, _project_version()})
    assert not stale, f"SECURITY.md pins stale version(s) {stale}; use {VERSION_PLACEHOLDER}"


def test_security_md_supports_only_the_current_minor_series():
    rows = _SUPPORTED_ROWS.findall((ROOT / "SECURITY.md").read_text(encoding="utf-8"))
    current = ".".join(_project_version().split(".")[:2])
    assert rows == [(current, "yes")], f"SECURITY.md supported-versions rows {rows}; expected only {current}.x as yes"

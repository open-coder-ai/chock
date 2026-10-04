"""A selection is read from a file, a `#s=` URL or a bare code, and refused unless it matches schema 1."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from install_fixtures import IDS, code, make_catalog, selection, write_selection

from chock.install import selection as sel
from chock.install import warnings

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


@pytest.fixture
def valid(tmp_path: Path) -> dict:
    root, ref = make_catalog(tmp_path)
    return selection(root, ref)


def test_file_url_and_bare_code_read_the_same_selection(valid: dict, tmp_path: Path) -> None:
    from_file = sel.load(str(write_selection(tmp_path / "chock.selection.yaml", valid)))
    assert from_file == valid
    assert sel.load(f"https://chock.sh/build#s={code(valid)}") == valid
    assert sel.load(code(valid)) == valid


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"surprise": 1}, "Additional properties"),
        ({"client": "cursor"}, "client"),
        ({"schema": 2}, "schema"),
        ({"policies": []}, "policies"),
    ],
)
def test_schema_errors_are_refused(valid: dict, change: dict, expected: str) -> None:
    with pytest.raises(sel.SelectionError, match=expected):
        sel.check({**valid, **change})


@pytest.mark.parametrize("ref", ["main", "abc1234", "A" * 40, "0" * 39])
def test_a_ref_that_is_not_40_lowercase_hex_is_refused(valid: dict, ref: str) -> None:
    with pytest.raises(sel.SelectionError, match="catalog/ref"):
        sel.check({**valid, "catalog": {**valid["catalog"], "ref": ref}})


def test_an_unknown_policy_key_is_refused(valid: dict) -> None:
    valid["policies"][0]["note"] = "x"
    with pytest.raises(sel.SelectionError, match="policies/0"):
        sel.check(valid)


def test_a_policy_listed_twice_is_refused(valid: dict) -> None:
    valid["policies"].append(dict(valid["policies"][0]))
    with pytest.raises(sel.SelectionError, match=f"more than once: {IDS[0]}"):
        sel.check(valid)


def test_a_code_that_is_not_base64url_json_is_refused() -> None:
    with pytest.raises(sel.SelectionError, match="base64url"):
        sel.load("not*a*code")


def test_the_digest_follows_what_is_installed_not_the_order(valid: dict) -> None:
    shuffled = {**valid, "policies": list(reversed(valid["policies"]))}
    assert sel.digest(shuffled) == sel.digest(valid)
    assert sel.digest({**valid, "policies": valid["policies"][:1]}) != sel.digest(valid)


def test_every_packaged_warning_rule_has_a_known_kind() -> None:
    assert {r["kind"] for r in warnings.load_rules()} <= set(warnings.KINDS)


RULES = [
    {"kind": "missing_partner", "policies": ["a-one", "a-two"], "says": "__PRESENT__ lacks __ABSENT__"},
    {"kind": "all_present", "policies": ["b-one", "b-two"], "says": "dup __PRESENT__"},
    {"kind": "file_absent", "policies": ["c-one"], "file": "allow.txt", "says": "__PRESENT__ needs __FILE__"},
    {"kind": "grade", "grade": "warn", "says": "__PRESENT__ observe"},
]


def test_each_warning_kind_fires_only_on_its_condition(tmp_path: Path) -> None:
    chosen = ["a-one", "b-one", "b-two", "c-one", "d-one"]
    found = warnings.warnings_for(chosen, {"d-one": "warn", "a-one": "block"}, tmp_path, RULES)
    assert found == ["a-one lacks a-two", "dup b-one and b-two", "c-one needs allow.txt", "d-one observe"]
    (tmp_path / "allow.txt").write_text("x", encoding="utf-8")
    quiet = warnings.warnings_for(["a-one", "a-two", "b-one", "c-one"], {}, tmp_path, RULES)
    assert quiet == []

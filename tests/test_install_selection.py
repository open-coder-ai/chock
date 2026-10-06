"""A selection is read from a file, a `#s=` URL or a bare code, checked against schema 1 or 2, and read as schema 2."""

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
    assert from_file == sel.upgrade(valid)
    assert sel.load(f"https://chock.sh/build#s={code(valid)}") == from_file
    assert sel.load(code(valid)) == from_file


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"surprise": 1}, "Additional properties"),
        ({"client": "cursor"}, "client"),
        ({"schema": 3}, "schema"),
        ({"schema": 2}, "bundle"),
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


def v2(valid: dict, **overrides: object) -> dict:
    """`valid` written as schema 2 by hand, the way the site emits it."""
    picks = [{"from": "catalog", **p} for p in valid["policies"]]
    data = {**valid, "schema": 2, "bundle": {"version": "1.2.0"}, "policies": picks}
    return {**data, **overrides}


def test_schema_1_reads_as_schema_2_with_the_default_bundle(valid: dict) -> None:
    upgraded = sel.upgrade(sel.check(valid))
    assert upgraded["schema"] == 2
    assert upgraded["bundle"] == {"name": "chock-guardrails", "version": "1.0.0"}
    assert all(p["from"] == "catalog" for p in upgraded["policies"])
    assert sel.check(upgraded) == upgraded
    assert sel.digest(upgraded) == sel.digest(valid), "an upgrade keeps the plugin's version"


@pytest.mark.parametrize("client", ["claude-code", "cursor", "codex", "copilot", "devin"])
def test_schema_2_names_any_of_the_five_clients(valid: dict, client: str) -> None:
    chosen = sel.upgrade(sel.check(v2(valid, client=client)))
    assert chosen["client"] == client
    assert chosen["bundle"] == {"name": "chock-guardrails", "version": "1.2.0"}


def test_schema_1_still_names_only_claude_code(valid: dict) -> None:
    with pytest.raises(sel.SelectionError, match="client"):
        sel.check({**valid, "client": "codex"})


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"client": "windsurf"}, "client"),
        ({"bundle": {"name": "Bad_Name", "version": "1.0.0"}}, "bundle/name"),
        ({"bundle": {"version": "1.0.0+abc"}}, "bundle/version"),
        ({"bundle": {"name": "chock-guardrails"}}, "version"),
        ({"bundle": {"version": "1.0.0", "extra": 1}}, "Additional properties"),
    ],
)
def test_schema_2_errors_are_refused_and_name_the_field(valid: dict, change: dict, expected: str) -> None:
    with pytest.raises(sel.SelectionError, match=expected):
        sel.check(v2(valid, **change))


def test_a_schema_2_catalog_entry_needs_its_pin_and_from(valid: dict) -> None:
    data = v2(valid)
    del data["policies"][0]["sha256"]
    with pytest.raises(sel.SelectionError, match="sha256"):
        sel.check(data)
    data = v2(valid)
    del data["policies"][0]["from"]
    with pytest.raises(sel.SelectionError, match="from"):
        sel.check(data)


def test_a_local_entry_is_valid_in_the_schema_and_needs_no_catalog(valid: dict) -> None:
    local = {"from": "local", "id": "my-guard", "path": "policies/my-guard"}
    data = v2(valid, policies=[local])
    del data["catalog"]
    assert sel.check(data)["policies"] == [local]


def test_catalog_entries_need_the_catalog(valid: dict) -> None:
    data = v2(valid)
    del data["catalog"]
    with pytest.raises(sel.SelectionError, match="catalog"):
        sel.check(data)


@pytest.mark.parametrize("path", ["/abs/x", "~/x", "../x", "a/../../x", "a/..", "C:/x", "a\\..\\x", ""])
def test_a_local_path_outside_the_selection_folder_is_refused(valid: dict, path: str) -> None:
    data = v2(valid, policies=[{"from": "local", "id": "my-guard", "path": path}])
    with pytest.raises(sel.SelectionError, match="path"):
        sel.check(data)


def test_a_local_entry_carries_no_content_field(valid: dict) -> None:
    entry = {"from": "local", "id": "my-guard", "path": "p", "content": "print(1)"}
    with pytest.raises(sel.SelectionError, match="Additional properties"):
        sel.check(v2(valid, policies=[entry]))


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
    {"kind": "client", "clients": ["codex"], "says": "codex fact"},
    {"kind": "overlap", "says": "__PRESENT__ also in __PLUGIN__ at __PATH__"},
]


def test_each_warning_kind_fires_only_on_its_condition(tmp_path: Path) -> None:
    chosen = ["a-one", "b-one", "b-two", "c-one", "d-one"]
    others = [("other", tmp_path / "other", ["b-one", "zz"]), ("clean", tmp_path / "clean", ["zz"])]
    ctx = warnings.Context(chosen, {"d-one": "warn", "a-one": "block"}, tmp_path, "codex", others)
    found = warnings.warnings_for(ctx, RULES)
    assert found == [
        "a-one lacks a-two",
        "dup b-one and b-two",
        "c-one needs allow.txt",
        "d-one observe",
        "codex fact",
        f"b-one also in other at {tmp_path / 'other'}",
    ]
    (tmp_path / "allow.txt").write_text("x", encoding="utf-8")
    quiet = warnings.warnings_for(warnings.Context(["a-one", "a-two", "b-one", "c-one"], {}, tmp_path, "cursor"), RULES)
    assert quiet == []

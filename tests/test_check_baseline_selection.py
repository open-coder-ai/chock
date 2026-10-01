"""A branch may not loosen a rule's verdict in `.chock/security.json` or `.chock/agentic-security.json`."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from chock.validation.checks_baseline import main
from chock.validation.selection_baseline import AGENTIC, JAVA, SelectionInvalidError, loosened

PACK = "java"
RULE = "java-xss-unescaped-template"


def _java(rules: dict | None = None, *, verdict: str | None = None, pack: str = PACK, version: int = 2) -> str:
    body: dict = {}
    if verdict:
        body["verdict"] = verdict
    if rules is not None:
        body["rules"] = rules
    return json.dumps({"version": version, "packs": {pack: body}})


def _agentic(rules: dict | None = None, *, verdict: str | None = None, pack: str = "exec") -> str:
    return _java(rules, verdict=verdict, pack=pack, version=1)


def _moves(kind, base: str | None, head: str | None) -> list[tuple]:
    return [(i.pack, i.rule, i.was, i.now) for i in loosened(kind, base, head)]


# --- java-security: absent means deny --------------------------------------------------------------


@pytest.mark.parametrize(("was", "now"), [("deny", "ask"), ("deny", "allow"), ("ask", "allow")])
def test_a_rule_moved_to_a_looser_verdict_is_loosened(was: str, now: str) -> None:
    assert _moves(JAVA, _java({RULE: was}), _java({RULE: now})) == [(PACK, RULE, was, now)]


@pytest.mark.parametrize(("was", "now"), [("allow", "deny"), ("ask", "deny"), ("allow", "ask"), ("deny", "deny")])
def test_a_rule_held_or_tightened_is_not(was: str, now: str) -> None:
    assert _moves(JAVA, _java({RULE: was}), _java({RULE: now})) == []


def test_a_rule_dropped_from_a_pack_that_denies_by_silence_is_tightened_not_loosened() -> None:
    assert _moves(JAVA, _java({RULE: "allow"}), _java({})) == []


def test_a_denying_rule_entry_dropped_stays_deny() -> None:
    assert _moves(JAVA, _java({RULE: "deny"}), _java({})) == []


def test_a_pack_verdict_loosened_is_loosened_for_every_rule() -> None:
    assert _moves(JAVA, _java(verdict="deny"), _java(verdict="allow")) == [(PACK, None, "deny", "allow")]


def test_a_pack_verdict_ends_its_rule_entries_in_java() -> None:
    """The runtime ignores `rules` beside a `verdict`, so the check does too."""
    assert _moves(JAVA, _java({RULE: "allow"}, verdict="deny"), _java({RULE: "deny"}, verdict="deny")) == []


def test_a_pack_omitted_from_a_deny_baseline_then_allowed_is_loosened() -> None:
    assert _moves(JAVA, None, _java(verdict="allow")) == [(PACK, None, "deny", "allow")]


def test_a_pack_removed_is_tightened_or_equal() -> None:
    assert _moves(JAVA, _java(verdict="allow"), json.dumps({"version": 2, "packs": {}})) == []


def test_a_deleted_file_hands_verdicts_to_the_user_level_file() -> None:
    """The runtime falls back to ~/.chock/security.json, so deletion is never read as all-deny."""
    for base in (_java({RULE: "deny"}), json.dumps({"version": 2, "packs": {}})):
        assert [i.render() for i in loosened(JAVA, base, None)] == [
            f"{JAVA.filename}: deleting the repo selection hands verdicts to ~/.chock/security.json"
        ]


def test_a_file_added_that_allows_a_rule_is_loosened() -> None:
    assert _moves(JAVA, None, _java({RULE: "ask"})) == [(PACK, RULE, "deny", "ask")]


def test_an_unchanged_file_is_silent_even_when_unreadable() -> None:
    assert loosened(JAVA, "{not json", "{not json") == []


def test_a_version_one_pack_verdict_loosened_is_found() -> None:
    v1 = _java(verdict="deny", pack="java", version=1)
    assert loosened(JAVA, v1, _java(verdict="allow", pack="java", version=1))


def test_a_version_one_file_moved_to_a_version_two_allow_is_found() -> None:
    v1 = _java(verdict="deny", pack="java", version=1)
    assert loosened(JAVA, v1, _java(verdict="allow"))


def test_a_version_one_file_kept_as_it_was_is_silent() -> None:
    v1 = _java({RULE: "ask"}, pack="java", version=1)
    assert loosened(JAVA, v1, _java({RULE: "ask"}, pack="java", version=1)) == []


# --- agentic-code-security: each rule has its own default ------------------------------------------


def test_an_agentic_rule_moved_from_deny_to_allow_is_loosened() -> None:
    assert _moves(AGENTIC, _agentic({"exec-x": "deny"}), _agentic({"exec-x": "allow"})) == [
        ("exec", "exec-x", "deny", "allow")
    ]


def test_an_agentic_rule_dropped_from_a_deny_entry_falls_to_a_default_that_may_allow() -> None:
    assert _moves(AGENTIC, _agentic({"exec-x": "deny"}), _agentic({})) == [("exec", "exec-x", "deny", None)]


def test_an_agentic_allow_entry_dropped_is_not_loosened() -> None:
    assert _moves(AGENTIC, _agentic({"exec-x": "allow"}), _agentic({})) == []


def test_an_agentic_pack_verdict_loosened_is_found_though_a_rule_entry_still_denies() -> None:
    """Rules override their pack in this reader, so the rule entry still says deny."""
    assert _moves(
        AGENTIC, _agentic({"exec-x": "deny"}, verdict="deny"), _agentic({"exec-x": "deny"}, verdict="allow")
    ) == [("exec", None, "deny", "allow")]


def test_an_agentic_file_added_with_an_allow_is_loosened() -> None:
    assert _moves(AGENTIC, None, _agentic({"exec-x": "allow"})) == [("exec", "exec-x", None, "allow")]


def test_an_agentic_file_deleted_falls_to_rule_defaults_not_a_user_file() -> None:
    """agentic-code-security has no user-level fallback: an absent file is every rule at its default."""
    assert loosened(AGENTIC, _agentic({"exec-x": "allow"}), None) == []
    assert _moves(AGENTIC, _agentic({"exec-x": "deny"}), None) == [("exec", "exec-x", "deny", None)]


def test_an_agentic_ask_is_not_a_verdict() -> None:
    with pytest.raises(SelectionInvalidError):
        loosened(AGENTIC, None, _agentic({"exec-x": "ask"}))


@pytest.mark.parametrize("version", ["true", "1.0"])
def test_a_version_equal_to_one_reads_as_version_one(version: str) -> None:
    head = f'{{"version": {version}, "packs": {{"java": {{"verdict": "allow"}}}}}}'
    assert loosened(JAVA, _java(verdict="deny", pack="java", version=1), head)


def test_a_version_equal_to_two_reads_as_version_two() -> None:
    head = json.dumps({"version": 2.0, "packs": {"spring": {"verdict": "allow"}}})
    assert _moves(JAVA, _java(verdict="deny", pack="spring"), head) == [("spring", None, "deny", "allow")]


@pytest.mark.parametrize("empty", ["[]", '""', "0", "false", "null"])
def test_falsy_packs_or_rules_read_as_empty_in_java(empty: str) -> None:
    base = _java({RULE: "allow"})
    assert loosened(JAVA, base, f'{{"version": 2, "packs": {empty}}}') == []
    assert loosened(JAVA, base, f'{{"version": 2, "packs": {{"{PACK}": {{"rules": {empty}}}}}}}') == []


def test_rules_beside_a_java_pack_verdict_are_not_read() -> None:
    head = json.dumps({"version": 2, "packs": {"android": {"verdict": "allow", "rules": []}}})
    assert _moves(JAVA, _java(verdict="deny", pack="android"), head) == [("android", None, "deny", "allow")]


@pytest.mark.parametrize("packs", ["null", "[]"])
def test_agentic_packs_must_be_an_object(packs: str) -> None:
    with pytest.raises(SelectionInvalidError):
        loosened(AGENTIC, None, f'{{"version": 1, "packs": {packs}}}')


@pytest.mark.parametrize("text", ["[]", '{"version": 3}', '{"version": 2.5}', '{"version": 2, "extra": 1}'])
def test_text_the_runtime_refuses_is_invalid(text: str) -> None:
    with pytest.raises(SelectionInvalidError):
        loosened(JAVA, None, text)


def test_a_list_version_does_not_crash() -> None:
    with pytest.raises(SelectionInvalidError):
        loosened(JAVA, None, '{"version": [2]}')


# --- over real revisions ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    (repo / ".chock").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@e")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    for name, body in files.items():
        (repo / name).write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    return repo


def test_a_branch_that_allows_a_denied_rule_fails(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = _repo(tmp_path, {JAVA.filename: _java({RULE: "deny"})})
    (repo / JAVA.filename).write_text(_java({RULE: "allow"}), encoding="utf-8")
    assert main(["--repo", str(repo), "--base", "main"]) == 1
    out = capsys.readouterr().out
    assert RULE in out
    assert "deny -> allow" in out


def test_a_branch_that_loosens_the_agentic_selection_fails(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {AGENTIC.filename: _agentic({"exec-x": "deny"})})
    (repo / AGENTIC.filename).write_text(_agentic({"exec-x": "allow"}), encoding="utf-8")
    assert main(["--repo", str(repo), "--base", "main"]) == 1


def test_a_branch_that_tightens_both_files_passes(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {JAVA.filename: _java({RULE: "allow"}), AGENTIC.filename: _agentic({"exec-x": "allow"})})
    (repo / JAVA.filename).write_text(_java({RULE: "deny"}), encoding="utf-8")
    (repo / AGENTIC.filename).write_text(_agentic({"exec-x": "deny"}), encoding="utf-8")
    assert main(["--repo", str(repo), "--base", "main"]) == 0


def test_a_branch_that_leaves_the_selections_alone_passes(tmp_path: Path) -> None:
    assert main(["--repo", str(_repo(tmp_path, {JAVA.filename: _java({RULE: "deny"})})), "--base", "main"]) == 0


def test_a_head_selection_the_runtime_would_refuse_fails(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = _repo(tmp_path, {JAVA.filename: _java({RULE: "deny"})})
    (repo / JAVA.filename).write_text("{broken", encoding="utf-8")
    assert main(["--repo", str(repo), "--base", "main"]) == 1
    assert "nothing was compared" in capsys.readouterr().out


def test_a_branch_that_deletes_the_java_selection_fails(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = _repo(tmp_path, {JAVA.filename: _java({RULE: "deny"})})
    (repo / JAVA.filename).unlink()
    assert main(["--repo", str(repo), "--base", "main"]) == 1
    assert "hands verdicts to ~/.chock/security.json" in capsys.readouterr().out


def test_a_branch_that_deletes_an_allowing_agentic_selection_passes(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {AGENTIC.filename: _agentic({"exec-x": "allow"})})
    (repo / AGENTIC.filename).unlink()
    assert main(["--repo", str(repo), "--base", "main"]) == 0


def _directory(path: Path, _: Path) -> None:
    path.mkdir()


def _link_to_missing(path: Path, outside: Path) -> None:
    os.symlink(outside / "absent.json", path)


def _link_to_present(path: Path, outside: Path) -> None:
    (outside / "allow.json").write_text(_java({RULE: "deny"}), encoding="utf-8")
    os.symlink(outside / "allow.json", path)


@pytest.mark.parametrize("kind", [JAVA, AGENTIC])
@pytest.mark.parametrize("swap", [_directory, _link_to_missing, _link_to_present])
def test_a_selection_path_that_is_not_a_regular_file_fails(tmp_path: Path, kind, swap, capsys) -> None:
    repo = _repo(tmp_path, {kind.filename: _java({RULE: "deny"}) if kind is JAVA else _agentic({"exec-x": "deny"})})
    (repo / kind.filename).unlink()
    swap(repo / kind.filename, tmp_path)
    assert main(["--repo", str(repo), "--base", "main"]) == 1
    assert "not a regular file" in capsys.readouterr().out


def test_a_linked_chock_directory_fails(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = _repo(tmp_path, {JAVA.filename: _java({RULE: "deny"})})
    (repo / ".chock").rename(tmp_path / "elsewhere")
    os.symlink(tmp_path / "elsewhere", repo / ".chock")
    assert main(["--repo", str(repo), "--base", "main"]) == 1
    assert "not a regular file" in capsys.readouterr().out

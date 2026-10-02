"""`--output` writes only a plain file; rule ids and help links in the log are safe whatever a contract holds."""

from __future__ import annotations

import json
from pathlib import Path

from test_sarif import POLICY, _contract, _finding, _repo, _valid

from chock.gate.sarif import build, rule_id
from chock.lifecycle import check_main


def _nested_repo(tmp_path: Path) -> Path:
    """A repo with room beside it in `tmp_path` for a link target outside it."""
    (tmp_path / "r").mkdir()
    return _repo(tmp_path / "r", [_finding(1)])


def _run(repo: Path, out: str) -> int:
    return check_main(["--repo", str(repo), "--event", "ci", "--base", "HEAD~1", "--format", "sarif", "--output", out])


def test_a_plain_file_is_written_and_replaced(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [_finding(1)])
    out = repo / "chock.sarif"
    out.write_text("old", encoding="utf-8")
    assert _run(repo, str(out)) == 1
    assert len(_valid(json.loads(out.read_text(encoding="utf-8")))["results"]) == 1
    assert [p.name for p in repo.iterdir() if p.name.startswith(".chock-sarif")] == []


def test_a_symlink_to_a_file_is_refused_and_its_target_untouched(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [_finding(1)])
    (repo / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (repo / "chock.sarif").symlink_to(repo / ".git" / "config")
    assert _run(repo, str(repo / "chock.sarif")) == 2
    assert (repo / ".git" / "config").read_text(encoding="utf-8") == "[core]\n"


def test_a_dangling_symlink_creates_nothing_at_its_target(tmp_path: Path) -> None:
    repo = _nested_repo(tmp_path)
    outside = tmp_path / "planted.txt"
    (repo / "chock.sarif").symlink_to(outside)
    assert _run(repo, str(repo / "chock.sarif")) == 2
    assert not outside.exists()


def test_a_symlinked_parent_directory_is_refused(tmp_path: Path) -> None:
    repo = _nested_repo(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (repo / "out").symlink_to(elsewhere, target_is_directory=True)
    assert _run(repo, str(repo / "out" / "chock.sarif")) == 2
    assert list(elsewhere.iterdir()) == []


def test_a_directory_or_dotdot_or_missing_parent_is_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [_finding(1)])
    (repo / "d").mkdir()
    assert _run(repo, str(repo / "d")) == 2
    assert _run(repo, str(repo / "d" / ".." / "x.sarif")) == 2
    assert _run(repo, str(repo / "nope" / "x.sarif")) == 2
    assert not (repo / "x.sarif").exists()


def test_a_relative_output_is_written_from_the_working_directory(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path, [])
    monkeypatch.chdir(repo)
    assert _run(repo, "chock.sarif") == 0
    assert (repo / "chock.sarif").is_file()


def test_rule_ids_are_one_safe_line_and_capped_but_stable() -> None:
    assert rule_id("p", "sql-concat") == "p/sql-concat"
    assert rule_id("p") == "p"
    hostile = rule_id("p", "a\r\n::error::b\u202e" + "x" * 500)
    assert "\n" not in hostile and "\u202e" not in hostile and len(hostile) <= 200


def test_a_hostile_contract_cannot_put_a_bad_id_or_link_in_the_log(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [_finding(1, rule="bad rule")])
    _contract(repo)
    contract = repo / ".agents" / "policies" / POLICY / "skills" / POLICY / "references" / "setup-contract.json"
    rules = [
        {
            "id": "bad\nid\u202e" + "y" * 400,
            "title": "t",
            "constraint": "c",
            "references": [
                "https://",
                "https:///x",
                "https://a b.example/x",
                "https://ex.example/\x00",
                "http://plain.example/",
                "https://ok.example/p",
            ],
        },
    ]
    contract.write_text(json.dumps({"rules": rules}), encoding="utf-8")
    run = _valid(build(repo, "HEAD~1")[0])
    (rule,) = [r for r in run["tool"]["driver"]["rules"] if r["id"] != f"{POLICY}/bad rule"]
    assert "\n" not in rule["id"] and len(rule["id"]) <= 200
    assert rule["helpUri"] == "https://ok.example/p"
    assert run["results"][0]["ruleIndex"] == [r["id"] for r in run["tool"]["driver"]["rules"]].index(
        f"{POLICY}/bad rule"
    )

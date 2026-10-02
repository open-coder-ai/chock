"""`chock check --event ci --format sarif`: a valid SARIF 2.1.0 log of the ci gates' findings."""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest
from conftest import init_repo
from jsonschema import Draft4Validator

from chock.gate.sarif import FINGERPRINT_KEY, build
from chock.lifecycle import check_main

SCHEMA = json.loads((Path(__file__).parent / "fixtures" / "sarif-schema-2.1.0.json").read_text(encoding="utf-8"))
POLICY = "demo-policy"
EMIT = textwrap.dedent(
    """\
    import json, sys
    payload = json.load(sys.stdin)
    findings = json.load(open(payload["repo_root"] + "/emit.json"))
    print(json.dumps({"findings": findings}))
    sys.exit(1 if findings else 0)
    """
)
CONTRACT = {
    "rules": [
        {
            "id": "sql-concat",
            "pack": "p",
            "title": "SQL built by concatenation",
            "constraint": "never(build): sql by concat",
            "cwe": [{"id": "CWE-89", "name": "SQL Injection"}, {"id": "bogus"}],
            "references": ["javascript:alert(1)", "https://example.com/sql"],
        },
        {"id": "other", "pack": "p", "title": "Other", "constraint": "c"},
    ]
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _finding(n: int = 1, **over: object) -> dict:
    return {"key": f"k{n}", "path": f"src/f{n:02}.py", "line": n, "message": f"bad {n}", "new": True, **over}


def _repo(tmp_path: Path, findings: list[dict], *, action: str = "block", rollout: str | None = None) -> Path:
    repo = init_repo(tmp_path)
    (repo / "emit.py").write_text(EMIT, encoding="utf-8")
    (repo / "emit.json").write_text(json.dumps(findings), encoding="utf-8")
    (repo / "base.txt").write_text("ok\n", encoding="utf-8")
    if rollout:
        (repo / ".chock").mkdir()
        (repo / ".chock" / "config.yaml").write_text(f"rollout: {rollout}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-qm", "change")
    gate = repo / ".chock" / "compiled" / POLICY / "ci-gate" / "gate.json"
    gate.parent.mkdir(parents=True, exist_ok=True)
    spec = {"kind": "script", "on": ["commit"], "action": action, "message": "fix it", "params": {"script": "emit.py"}}
    gate.write_text(json.dumps(spec), encoding="utf-8")
    return repo


def _valid(log: dict) -> dict:
    Draft4Validator(SCHEMA).validate(log)
    return log["runs"][0]


def _contract(repo: Path) -> None:
    path = repo / ".agents" / "policies" / POLICY / "skills" / POLICY / "references" / "setup-contract.json"
    path.parent.mkdir(parents=True)
    (path.parent.parent.parent.parent / "manifest.yaml").write_text("id: demo-policy\n", encoding="utf-8")
    path.write_text(json.dumps(CONTRACT), encoding="utf-8")


def test_a_blocking_finding_is_a_valid_error_result(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [_finding(3, rule="sql-concat")])
    _contract(repo)
    log, code = build(repo, "HEAD~1")
    run = _valid(log)
    assert code == 1
    driver = run["tool"]["driver"]
    assert driver["name"] == "chock" and driver["version"] and driver["informationUri"].startswith("https://")
    assert [rule["id"] for rule in driver["rules"]] == [f"{POLICY}/sql-concat", f"{POLICY}/other"]
    sql = driver["rules"][0]
    assert sql["properties"]["tags"] == ["chock", f"chock/{POLICY}", "external/cwe/cwe-89"]
    assert sql["helpUri"] == "https://example.com/sql"
    assert sql["shortDescription"]["text"] == "SQL built by concatenation"
    (result,) = run["results"]
    assert (result["ruleId"], result["ruleIndex"], result["level"]) == (f"{POLICY}/sql-concat", 0, "error")
    assert result["message"]["text"] == "bad 3"
    assert result["locations"][0]["physicalLocation"] == {
        "artifactLocation": {"uri": "src/f03.py"},
        "region": {"startLine": 3},
    }
    assert result["properties"]["rolloutHeld"] is False


def test_fingerprints_are_stable_across_runs_and_ignore_the_line(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [_finding(1), _finding(2)])
    first = [r["partialFingerprints"][FINGERPRINT_KEY] for r in build(repo, "HEAD~1")[0]["runs"][0]["results"]]
    (repo / "emit.json").write_text(json.dumps([_finding(1, line=40), _finding(2, line=41)]), encoding="utf-8")
    second = [r["partialFingerprints"][FINGERPRINT_KEY] for r in build(repo, "HEAD~1")[0]["runs"][0]["results"]]
    assert first == second and len(set(first)) == 2


def test_the_same_finding_twice_gets_two_fingerprints(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [_finding(1), _finding(1, line=9)])
    prints = [r["partialFingerprints"][FINGERPRINT_KEY] for r in build(repo, "HEAD~1")[0]["runs"][0]["results"]]
    assert len(set(prints)) == 2


@pytest.mark.parametrize(
    ("action", "level", "code"), [("block", "error", 1), ("ask", "warning", 0), ("warn", "note", 0)]
)
def test_the_declared_action_maps_to_the_sarif_level(tmp_path: Path, action: str, level: str, code: int) -> None:
    repo = _repo(tmp_path, [_finding(1)], action=action)
    log, exit_code = build(repo, "HEAD~1")
    assert [r["level"] for r in _valid(log)["results"]] == [level]
    assert exit_code == code


def test_a_finding_the_rollout_holds_still_appears_at_the_level_it_would_have(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [_finding(1)], rollout="observe")
    log, code = build(repo, "HEAD~1")
    (result,) = _valid(log)["results"]
    assert code == 0
    assert result["level"] == "error"
    assert result["properties"]["rolloutHeld"] is True
    assert result["properties"]["verdict"] == "warn"


def test_a_clean_change_is_a_valid_empty_log(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [])
    log, code = build(repo, "HEAD~1")
    assert (_valid(log)["results"], code) == ([], 0)


def test_paths_never_leave_the_repo_and_are_posix(tmp_path: Path) -> None:
    items = [
        _finding(1, path="../escape.py"),
        _finding(2, path="/etc/passwd"),
        _finding(3, path="win\\dir\\a b.py"),
        _finding(4, path=str(tmp_path / "abs.py")),
    ]
    repo = _repo(tmp_path, items)
    uris = {
        r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        for r in build(repo, "HEAD~1")[0]["runs"][0]["results"]
    }
    assert uris == {".chock/compiled/demo-policy/ci-gate/gate.json", "win/dir/a%20b.py", "abs.py"}
    assert all(not u.startswith("/") and ".." not in u.split("/") for u in uris)


def test_a_fallback_location_has_no_region(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [_finding(5, path="../escape.py")])
    (result,) = _valid(build(repo, "HEAD~1")[0])["results"]
    assert "region" not in result["locations"][0]["physicalLocation"]


def test_message_text_has_no_control_or_invisible_characters(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [_finding(1, message="a\r\n::error::b\x00\x1b[31m\u202e c\ud800 d")])
    log, _ = build(repo, "HEAD~1")
    (result,) = _valid(log)["results"]
    text = result["message"]["text"]
    assert text == "a ::error::b [31m c? d"
    assert text.isprintable()
    json.dumps(log).encode("utf-8")


def test_a_declarative_gate_reports_the_file_that_matched(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "a.txt").write_text("ok\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    (repo / "todo.txt").write_text("TODO later\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")
    gate = repo / ".chock" / "compiled" / "no-todo" / "ci-gate" / "gate.json"
    gate.parent.mkdir(parents=True)
    spec = {
        "kind": "content_regex",
        "on": ["commit"],
        "action": "block",
        "message": "no TODO",
        "params": {"content_pattern": "TODO"},
    }
    gate.write_text(json.dumps(spec), encoding="utf-8")
    log, code = build(repo, "HEAD~1")
    run = _valid(log)
    (result,) = run["results"]
    assert (code, result["ruleId"], result["level"]) == (1, "no-todo", "error")
    assert result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "todo.txt"
    assert result["message"]["text"] == "content pattern: no TODO"
    assert [rule["id"] for rule in run["tool"]["driver"]["rules"]] == ["no-todo"]


def test_a_base_that_does_not_resolve_is_undecided_not_clean(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [])
    log, code = build(repo, "origin/missing")
    run = _valid(log)
    assert code == 2
    assert run["invocations"][0]["executionSuccessful"] is False
    assert run["results"] == []


def test_the_cli_writes_the_file_and_keeps_the_gate_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = _repo(tmp_path, [_finding(1)])
    out = tmp_path / "out" / "chock.sarif"
    out.parent.mkdir()
    argv = ["--repo", str(repo), "--event", "ci", "--base", "HEAD~1", "--format", "sarif", "--output", str(out)]
    assert check_main(argv) == 1
    assert capsys.readouterr().out == ""
    assert len(_valid(json.loads(out.read_text(encoding="utf-8")))["results"]) == 1


def test_the_cli_prints_the_log_alone_on_stdout(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = _repo(tmp_path, [])
    assert check_main(["--repo", str(repo), "--event", "ci", "--base", "HEAD~1", "--format", "sarif"]) == 0
    assert _valid(json.loads(capsys.readouterr().out))["results"] == []


@pytest.mark.parametrize(
    "argv",
    [
        ["--format", "sarif"],
        ["--format", "sarif", "--event", "ci"],
        ["--format", "sarif", "--event", "commit", "--base", "HEAD"],
        ["--format", "sarif", "--event", "ci", "--base", "HEAD", "--only", "validate"],
        ["--output", "x.sarif"],
    ],
)
def test_the_cli_refuses_a_sarif_run_it_cannot_make(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        check_main(argv)
    assert excinfo.value.code == 2

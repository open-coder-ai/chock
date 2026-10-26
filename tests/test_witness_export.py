"""`chock witness export`: redaction, the bundle's fields, and the agentseam evidence issue per client."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import pytest
from agentseam import matrix as agentseam_matrix
from history_support import SECRET

from chock import witness_export as we
from chock.cli import main as cli_main
from chock.install import package, place, warnings


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "home"
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("USERPROFILE", str(folder))
    return folder


def _write(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def _record(agent: str, **fields: object) -> dict[str, object]:
    base = {"ts": "2026-10-13T10:00:00Z", "route": "plugin", "agent": agent, "event": "tool_use"}
    return {**base, "policy_id": "p", "verdict": "block", "plugin": "chock", "plugin_version": "1.0.0+abc", **fields}


def test_export_redacts_secrets_and_the_home_folder(
    tmp_path: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    trace = {"command": f"deploy --key {SECRET}", "path": str(home / "work" / "app.py")}
    _write(home / ".chock" / "log" / "goose" / "events.jsonl", [_record("goose", level="debug", trace=trace)])
    _write(home / ".chock" / "log" / "grok" / "events.jsonl", [_record("grok")])
    out = tmp_path / "bundle.json"

    assert cli_main(["witness", "export", "--client", "goose", "--out", str(out), "--repo", str(tmp_path)]) == 0

    text = out.read_text(encoding="utf-8")
    assert SECRET not in text
    assert str(home) not in text
    doc = json.loads(text)
    assert [r["agent"] for r in doc["records"]] == ["goose"]
    assert doc["records"][0]["trace"] == {"command": "deploy --key [redacted]", "path": "~/work/app.py"}
    assert doc["plugins"] == ["chock 1.0.0+abc"]
    assert doc["events"] == ["tool_use"]
    assert set(doc) >= {"agent_version", "platform", "engine", "catalog_refs", "issue"}
    printed = capsys.readouterr().out
    assert "Nothing was uploaded" in printed
    assert "Attach it to: https://github.com/open-coder-ai/agentseam/issues/177" in printed


def test_redaction_covers_a_windows_home() -> None:
    home = "C:\\Users\\me"
    record = {"trace": {"path": "C:\\Users\\me\\repo\\a.py", "other": "C:/Users/me/repo/b.py"}, "n": 3}
    assert we.redact(record, home) == {"trace": {"path": "~\\repo\\a.py", "other": "~/repo/b.py"}, "n": 3}


def test_a_root_home_is_not_rewritten() -> None:
    assert we.redact("/usr/bin/git", "/") == "/usr/bin/git"


def test_export_reads_the_plugin_marker_for_the_catalog_ref(tmp_path: Path, home: Path) -> None:
    marker = place.plugin_dir("goose", place.default_dest("goose"), "chock") / package.MARKER
    assert home in marker.parents
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"catalog": {"source": "https://example.test/cat", "ref": "abc123"}}), "utf-8")

    assert we.catalog_refs("goose", [_record("goose")], tmp_path) == ["https://example.test/cat@abc123"]
    assert we.catalog_refs("goose", [_record("goose", plugin="../chock")], tmp_path) == []


def _matrix_issue(agent: str) -> str | None:
    notes = str(agentseam_matrix.MATRIX[agent].get("notes") or "")
    return we._issue_in(notes)


@pytest.mark.parametrize("agent", sorted(a for a in agentseam_matrix.MATRIX if _matrix_issue(a)))
def test_issue_url_follows_agentseams_matrix_row(agent: str) -> None:
    assert we.issue_url(agent) == _matrix_issue(agent)


def test_issue_url_falls_back_to_chocks_install_warnings() -> None:
    by_client = {}
    for rule in warnings.load_rules():
        found = we._issue_in(str(rule.get("says") or ""))
        by_client.update({client: found for client in rule.get("clients") or () if found})
    agents = we.install_agents()
    assert by_client, "install warnings name no evidence issue: the fallback is untested"
    for client, url in by_client.items():
        agent = agents[client]
        assert we.issue_url(agent) == (_matrix_issue(agent) or url), client


@pytest.mark.parametrize(
    ("client", "issue"),
    [
        ("goose", "issues/177"),
        ("grok", "issues/188"),
        ("antigravity", "issues/new?template=evidence-report.yml"),  # witnessed: no Evidence wanted warning
        ("gemini", "issues/new?template=evidence-report.yml"),
        ("kimi-code", "issues/135"),
        ("factory-droid", "issues/184"),
        ("openhands", "issues/181"),
        ("claude-code", "issues/new?template=evidence-report.yml"),
    ],
)
def test_issue_url_per_client(client: str, issue: str) -> None:
    agent = we.resolve_agent(client)
    assert agent is not None
    assert we.issue_url(agent) == f"https://github.com/open-coder-ai/agentseam/{issue}"


def test_every_issue_url_is_an_agentseam_issue() -> None:
    pattern = re.compile(we.DATA["issue_url_pattern"] + "$")
    for agent in agentseam_matrix.MATRIX:
        url = we.issue_url(agent)
        assert pattern.match(url) or url == we.DATA["new_issue_url"], agent


def test_an_unknown_client_is_refused(tmp_path: Path, home: Path) -> None:
    assert cli_main(["witness", "export", "--client", "no-such-agent", "--out", str(tmp_path / "x.json")]) == 2
    assert not (tmp_path / "x.json").exists()


def test_an_existing_file_is_refused_and_left_byte_identical(tmp_path: Path, home: Path) -> None:
    target = tmp_path / ".claude" / "settings.json"
    target.parent.mkdir()
    original = b'{"hooks": {"PreToolUse": []}}\n'
    target.write_bytes(original)

    assert cli_main(["witness", "export", "--client", "goose", "--out", str(target), "--repo", str(tmp_path)]) == 2
    assert target.read_bytes() == original


@pytest.mark.parametrize("name", ["hooks.toml", "run.sh", "settings", "x.json.bak"])
def test_out_must_be_a_json_file(tmp_path: Path, home: Path, name: str) -> None:
    target = tmp_path / name
    assert cli_main(["witness", "export", "--client", "goose", "--out", str(target), "--repo", str(tmp_path)]) == 2
    assert not target.exists()


def test_the_default_name_is_written_owner_only(tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli_main(["witness", "export", "--client", "goose", "--repo", str(tmp_path)]) == 0
    written = we.default_out("goose")
    assert json.loads((tmp_path / written).read_text(encoding="utf-8"))["agent"] == "goose"
    if os.name == "posix":
        assert (tmp_path / written).stat().st_mode & 0o777 == 0o600
    assert cli_main(["witness", "export", "--client", "goose", "--repo", str(tmp_path)]) == 2


def test_fingerprints_in_an_export_cannot_be_confirmed_by_guessing(home: Path) -> None:

    guess = hashlib.sha256(b"/home/alice/.ssh/id_rsa").hexdigest()
    command = hashlib.sha256(b"mysql -uroot -pletmein db").hexdigest()
    records = [
        _record("claude-code", target=f"outside:sha256:{guess}"),
        _record("claude-code", target=f"mysql sha256:{command}"),
        _record("claude-code", target=f"outside:sha256:{guess}"),
        _record("claude-code", target="src/app.py"),
    ]

    made = we.bundle("claude-code", records, home, None)
    text = json.dumps(made)
    targets = [r["target"] for r in made["records"]]

    assert guess not in text
    assert command not in text
    assert targets[0] == targets[2] != targets[1]
    assert targets[3] == "src/app.py"
    assert targets[1].startswith("mysql ")
    assert we.bundle("claude-code", records, home, None)["records"][0]["target"] != targets[0]

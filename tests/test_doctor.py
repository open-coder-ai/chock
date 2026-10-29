"""OBS-1: `chock doctor` per client and route, PASS/WARN/FAIL with fixes, and the engine stamp it reads."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agentseam import recordings
from runtime_support import write_runtime

from chock import __version__, vendors
from chock.doctor import checks, cli
from chock.doctor.targets import Target, plugin_targets, sync_targets
from chock.gate import runtime_bundle
from chock.hooks import launch
from chock.install import package
from chock.scaffold.pin import engine_commit

AGENT = "claude_code"
CLIENT = "claude-code"


@pytest.fixture
def home(tmp_path, monkeypatch):
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("USERPROFILE", str(folder))
    monkeypatch.delenv("CHOCK_LOG_LEVEL", raising=False)
    monkeypatch.delenv("CHOCK_GATE_LOG", raising=False)
    monkeypatch.setattr(checks, "_python_version", lambda name: (3, 12) if name == "python3" else None)
    return folder


def _sync_repo(tmp_path: Path, agent: str = AGENT) -> Path:
    repo = tmp_path / "repo"
    (repo / ".chock" / "bin").mkdir(parents=True)
    write_runtime(repo / ".chock" / "bin" / f"{agent}.py", agent)
    (repo / launch.LAUNCHER_REL).write_text(launch.launcher_text(), encoding="utf-8")
    config = repo / {"claude_code": ".claude/settings.json", "windsurf": vendors.config_path("windsurf")}[agent]
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"hooks": {"X": [{"command": f".chock/bin/{agent}.py"}]}}), encoding="utf-8")
    return repo


def _plugin(home: Path, *, version: str = __version__) -> Path:
    folder = home / ".chock" / "marketplace" / CLIENT / "claude" / "obs-bundle"
    (folder / "scripts").mkdir(parents=True)
    write_runtime(folder / "scripts" / f"{AGENT}.py", AGENT)
    (folder / "scripts" / launch.PLUGIN_LAUNCHER).write_text(launch.launcher_text(), encoding="utf-8")
    (folder / "hooks").mkdir()
    (folder / "hooks" / "hooks.json").write_text(json.dumps({"c": "scripts/claude_code.py"}), encoding="utf-8")
    (folder / ".claude-plugin").mkdir()
    (folder / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "obs-bundle", "version": "1"}))
    marker = {"client": CLIENT, "marker": {"engine": {"version": version, "commit": engine_commit()}}}
    (folder / package.MARKER).write_text(json.dumps(marker), encoding="utf-8")
    return folder


def _by_name(found: list[checks.Check]) -> dict[str, checks.Check]:
    return {c.name: c for c in found}


def _log(path: Path, *lines: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")


def test_a_current_sync_install_passes_hooks_launcher_and_engine(tmp_path, home):
    repo = _sync_repo(tmp_path)
    [target] = sync_targets(repo)
    found = _by_name(checks.run(target, repo))
    assert [found[n].status for n in ("hooks", "launcher", "engine")] == ["PASS"] * 3


def test_a_runtime_from_another_engine_fails_with_the_sync_fix(tmp_path, home):
    repo = _sync_repo(tmp_path)
    (repo / ".chock" / "bin" / f"{AGENT}.py").write_text("# older engine\n", encoding="utf-8")
    [target] = sync_targets(repo)
    engine = _by_name(checks.run(target, repo))["engine"]
    assert engine.status == "FAIL"
    assert "chock sync --repo" in engine.fix


@pytest.mark.parametrize("stale", ["missing", "other-version"])
def test_a_missing_or_stale_shared_runtime_fails_the_engine_check(tmp_path, home, stale):
    repo = _sync_repo(tmp_path)
    shared = repo / ".chock" / "bin" / runtime_bundle.SHARED_FILE
    if stale == "missing":
        shared.unlink()
    else:
        shared.write_text("# older engine\n", encoding="utf-8")
    [target] = sync_targets(repo)
    engine = _by_name(checks.run(target, repo))["engine"]
    assert (engine.status, runtime_bundle.SHARED_FILE in engine.detail) == ("FAIL", True), engine
    assert "chock sync --repo" in engine.fix


def test_missing_launcher_runtime_or_python_fail(tmp_path, home, monkeypatch):
    repo = _sync_repo(tmp_path)
    (repo / launch.LAUNCHER_REL).unlink()
    [target] = sync_targets(repo)
    assert _by_name(checks.run(target, repo))["launcher"].status == "FAIL"
    (repo / ".chock" / "bin" / f"{AGENT}.py").unlink()
    assert checks.hooks_present(target).status == "FAIL"
    (repo / launch.LAUNCHER_REL).write_text(launch.launcher_text(), encoding="utf-8")
    monkeypatch.setattr(checks, "_python_version", lambda name: (3, 10))
    assert checks.launcher(target).name == "python"
    assert checks.launcher(target).status == "FAIL"


def test_a_plugin_install_is_checked_against_its_recorded_engine(tmp_path, home):
    _plugin(home)
    [target] = plugin_targets()
    assert (target.client, target.route) == (CLIENT, "plugin")
    assert _by_name(checks.run(target, tmp_path))["engine"].status == "PASS"


def test_a_plugin_recorded_by_another_engine_version_warns_with_the_rebuild_fix(tmp_path, home):
    _plugin(home, version="0.0.1")
    [target] = plugin_targets()
    engine = _by_name(checks.run(target, tmp_path))["engine"]
    assert engine.status == "WARN"
    assert "chock install" in engine.fix


def test_an_install_marker_stamps_the_building_engine():
    block = package.marker({"client": CLIENT}, {})["marker"]
    assert block["engine"] == {"version": __version__, "commit": engine_commit()}


def test_agents_without_a_session_start_event_list_no_heartbeat_available(tmp_path, home):
    repo = _sync_repo(tmp_path, "windsurf")
    [target] = sync_targets(repo)
    beat = _by_name(checks.run(target, repo))["heartbeat"]
    assert (beat.status, beat.detail.startswith("no heartbeat available")) == ("INFO", True)


def test_hook_records_without_a_heartbeat_warn(tmp_path, home):
    repo = _sync_repo(tmp_path)
    _log(repo / ".chock/log/gate-events.jsonl", {"ts": "2026-10-13T00:00:01Z", "agent": AGENT, "surface": "stop"})
    [target] = sync_targets(repo)
    found = _by_name(checks.run(target, repo))
    assert found["heartbeat"].status == "WARN"
    assert found["heartbeat"].detail == "hook records but no session_start heartbeat"
    assert found["last fired"].detail == "stop 2026-10-13T00:00:01Z"


@pytest.mark.parametrize(("level", "status"), [("debug", "WARN"), ("info", "WARN"), ("off", "INFO")])
def test_heartbeats_with_no_hook_since_warn_wherever_allows_are_logged(tmp_path, home, level, status):
    repo = _sync_repo(tmp_path)
    (repo / ".chock" / "chock-log.json").write_text(json.dumps({"level": level}), encoding="utf-8")
    beat = {"ts": "2026-10-13T00:00:02Z", "agent": AGENT, "event": "session_start", "route": "sync"}
    _log(repo / ".chock/log/gate-events.jsonl", {"ts": "2026-10-13T00:00:01Z", "agent": AGENT, "surface": "stop"}, beat)
    [target] = sync_targets(repo)
    beat = _by_name(checks.run(target, repo))["heartbeat"]
    assert beat.status == status
    assert "debug" not in f"{beat.detail} {beat.fix}"


def test_a_hook_since_the_last_heartbeats_passes(tmp_path, home):
    repo = _sync_repo(tmp_path)
    beat = {"ts": "2026-10-13T00:00:01Z", "agent": AGENT, "event": "session_start", "route": "sync"}
    _log(repo / ".chock/log/gate-events.jsonl", beat, {"ts": "2026-10-13T00:00:02Z", "agent": AGENT, "surface": "stop"})
    [target] = sync_targets(repo)
    assert _by_name(checks.run(target, repo))["heartbeat"].status == "PASS"


def test_the_client_version_is_compared_only_when_given(tmp_path, home):
    repo = _sync_repo(tmp_path)
    [target] = sync_targets(repo)
    witnessed = recordings.versions(AGENT)[-1]
    assert checks.client_version(target, None).status == "INFO"
    assert checks.client_version(target, witnessed).status == "PASS"
    assert checks.client_version(target, "0.0.0-unseen").status == "WARN"


def test_codex_trust_is_named_not_guessed(tmp_path, home):
    repo = _sync_repo(tmp_path)
    [target] = sync_targets(repo)
    codex = Target("codex_cli", "codex_cli", "sync", repo, repo / "r", repo / "l", repo / "h")
    trust = checks.trust(codex)
    assert trust is not None
    assert (trust.status, "/hooks" in trust.fix) == ("INFO", True)
    assert checks.trust(target) is None


def test_the_command_exits_1_on_a_fail_0_otherwise_and_filters_by_client(tmp_path, home, capsys):
    repo = _sync_repo(tmp_path)
    assert cli.main(["--repo", str(repo), "--client", AGENT]) == 0
    assert f"{AGENT} [sync]" in capsys.readouterr().out
    assert cli.main(["--repo", str(repo), "--client", "cursor"]) == 1
    assert "no chock hooks found for cursor" in capsys.readouterr().out
    (repo / launch.LAUNCHER_REL).unlink()
    assert cli.main(["--repo", str(repo), "--json"]) == 1
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {(r["client"], r["route"]) for r in rows} == {(AGENT, "sync")}


def test_a_healthy_install_of_an_unwitnessed_client_reports_info_and_exits_0(tmp_path, home, capsys):
    repo = _sync_repo(tmp_path, "windsurf")
    [target] = sync_targets(repo)
    assert not recordings.versions("windsurf")
    assert checks.client_version(target, None).status == "INFO"
    found = checks.run(target, repo)
    assert {c.status for c in found} <= {"PASS", "INFO"}
    assert "INFO" in {c.status for c in found}
    assert cli.main(["--repo", str(repo)]) == 0
    assert "WARN" not in capsys.readouterr().out

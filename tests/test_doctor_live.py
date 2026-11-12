"""W1-D: `chock doctor --live` runs each installed pre-tool hook as its client would, on a canary and a harmless call."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from conftest import baseline_policy, init_repo

from chock.doctor import checks, cli, live
from chock.doctor.payloads import DENY_ON_THE_WIRE, PAYLOADS, payload
from chock.doctor.targets import ROUTE_PLUGIN, Target, sync_targets
from chock.hooks import launch
from chock.scaffold.recompile import recompile

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")

POLICY = "block-no-verify"
AGENT = "claude_code"


@pytest.fixture
def synced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository `sync` wired for Claude Code with one in-agent policy, and a private HOME."""
    (tmp_path / "repo").mkdir()
    repo = init_repo(tmp_path / "repo")
    shutil.copytree(baseline_policy(POLICY), repo / ".agents" / "policies" / POLICY)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("CHOCK_GATE_LOG", raising=False)
    monkeypatch.setenv("CHOCK_LOG_LEVEL", "info")
    recompile(repo, ["claude"], skip_hooks=False)
    return repo


def _tree(repo: Path) -> dict[str, bytes]:
    return {
        p.relative_to(repo).as_posix(): p.read_bytes() for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts
    }


def _live(repo: Path) -> dict[str, checks.Check]:
    [target] = [t for t in sync_targets(repo) if t.agent == AGENT]
    return {c.name: c for c in live.run(target, repo)}


def test_an_installed_policy_refuses_its_own_canary_and_allows_a_harmless_command(synced: Path) -> None:
    found = _live(synced)
    assert found[live.REFUSES].status == checks.PASS, found
    assert POLICY in found[live.REFUSES].detail
    assert found[live.ALLOWS].status == checks.PASS, found


def test_the_probe_writes_nothing_in_the_repo_or_its_decision_log(synced: Path) -> None:
    before = _tree(synced)
    _live(synced)
    assert _tree(synced) == before


def test_the_cli_prints_both_rows_and_json_carries_them(synced: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--repo", str(synced), "--client", AGENT, "--live"]) in (0, 1)
    text = capsys.readouterr().out
    assert f"PASS  {live.REFUSES}: {POLICY} refused" in text
    assert f"PASS  {live.ALLOWS}:" in text
    cli.main(["--repo", str(synced), "--client", AGENT, "--live", "--json"])
    [row] = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    statuses = {c["name"]: c["status"] for c in row["checks"]}
    assert statuses[live.REFUSES] == statuses[live.ALLOWS] == checks.PASS


def test_without_live_no_hook_is_run(synced: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["--repo", str(synced), "--client", AGENT])
    assert "live:" not in capsys.readouterr().out


def test_a_broken_launcher_path_fails_both_rows_with_the_sync_fix(synced: Path) -> None:
    (synced / launch.LAUNCHER_REL).unlink()
    found = _live(synced)
    for name in (live.REFUSES, live.ALLOWS):
        assert found[name].status == checks.FAIL, found
        assert found[name].fix == f"run `chock sync --repo {synced}`"
    assert "launch.sh" in found[live.REFUSES].detail


def test_a_refusal_by_anything_but_the_policy_is_not_a_pass(synced: Path) -> None:
    settings = synced / ".claude" / "settings.json"
    doc = json.loads(settings.read_text(encoding="utf-8"))
    for group in doc["hooks"]["PreToolUse"]:
        for hook in group["hooks"]:
            hook["command"] = hook["command"].replace(".chock/bin/claude_code.py", ".chock/bin/gone.py")
    settings.write_text(json.dumps(doc), encoding="utf-8")
    found = _live(synced)
    assert found[live.REFUSES].status == checks.FAIL
    assert found[live.ALLOWS].status == checks.FAIL


def test_no_guard_on_the_shell_tool_is_reported_skipped(synced: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live, "canary", lambda *_: None)
    found = _live(synced)
    assert found[live.LIVE].status == checks.INFO
    assert found[live.LIVE].detail == "skipped (no in-agent policy installed on its shell tool)"
    assert found[live.ALLOWS].status == checks.PASS


def test_a_hooks_file_with_no_pre_tool_command_fails(synced: Path) -> None:
    (synced / ".claude" / "settings.json").write_text(json.dumps({"hooks": {}}), encoding="utf-8")
    [target] = [t for t in sync_targets(synced) if t.agent == AGENT]
    [row] = live.run(target, synced)
    assert row.status == checks.FAIL
    assert "no pre-tool hook command" in row.detail


def test_a_plugin_command_has_its_root_token_filled_in_and_its_matcher_honoured(tmp_path: Path) -> None:
    folder = tmp_path / "plugin dir"
    hooks = folder / "hooks" / "hooks.json"
    hooks.parent.mkdir(parents=True)
    doc = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"command": 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/launch.sh" --guard x'}]},
                {"matcher": "Write", "hooks": [{"command": "never"}]},
            ],
            "Stop": [{"hooks": [{"command": "stop"}]}],
        }
    }
    hooks.write_text(json.dumps(doc), encoding="utf-8")
    target = Target("claude-code", AGENT, ROUTE_PLUGIN, folder, folder, folder, hooks)
    assert live.commands(target) == [("command", f'sh "{folder.as_posix()}/scripts/launch.sh" --guard x')]


def test_copilot_s_per_shell_entry_is_read() -> None:
    assert live._entry({"bash": "b", "powershell": "p"}) in (("bash", "b"), ("powershell", "p"))
    assert live._entry({"command": "c", "bash": "b"}) == ("command", "c")


def test_the_payloads_are_one_source_with_the_old_test_module() -> None:
    import runtime_payloads

    assert runtime_payloads.PAYLOADS is PAYLOADS
    assert runtime_payloads.DENY_ON_THE_WIRE is DENY_ON_THE_WIRE
    assert set(PAYLOADS) == set(DENY_ON_THE_WIRE)
    assert PAYLOADS["cursor"]("ls")["workspace_roots"] == ["/x"]
    assert payload("factory_droid", "ls", "/r")["transcript_path"] == "/r/.factory/projects/x/session.jsonl"


def test_the_probe_names_its_own_session() -> None:
    for agent in PAYLOADS:
        sent = live._probe(agent, "ls", Path("/r"))
        assert live.PROBE_SESSION in sent.values(), agent

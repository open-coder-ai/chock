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


#: What a foreign hook command or an edited launcher would leave behind if `--live` ran it.
MARKER = "live-marker"
WRITE_MARKER = f"echo x > {MARKER}"


def _settings(repo: Path) -> tuple[Path, dict]:
    path = repo / ".claude" / "settings.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def test_a_foreign_hook_command_is_counted_never_run(synced: Path) -> None:
    path, doc = _settings(synced)
    doc["hooks"]["PreToolUse"].append({"matcher": "Bash", "hooks": [{"type": "command", "command": WRITE_MARKER}]})
    path.write_text(json.dumps(doc), encoding="utf-8")
    found = _live(synced)
    assert not (synced / MARKER).exists()
    assert found[live.LIVE].status == checks.INFO
    assert found[live.LIVE].detail == "1 other hook command(s) not run (not chock's)"
    assert found[live.REFUSES].status == found[live.ALLOWS].status == checks.PASS


def test_an_edited_launcher_runs_nothing(synced: Path) -> None:
    launcher = synced / launch.LAUNCHER_REL
    launcher.write_text(f"{WRITE_MARKER}\n" + launcher.read_text(encoding="utf-8"), encoding="utf-8")
    [row] = _live(synced).values()
    assert not (synced / MARKER).exists()
    assert row.detail == "skipped (runtime is not this engine's)"
    assert row.fix == f"run `chock sync --repo {synced}`"


def test_a_missing_launcher_runs_nothing(synced: Path) -> None:
    (synced / launch.LAUNCHER_REL).unlink()
    [row] = _live(synced).values()
    assert row.detail == "skipped (runtime is not this engine's)"


def test_a_tampered_pinned_index_fails_both_rows_with_the_sync_fix(synced: Path) -> None:
    for index in (synced / ".chock" / "bin" / "index").glob("claude_code-*.json"):
        index.write_text(index.read_text(encoding="utf-8") + " ", encoding="utf-8")
    found = _live(synced)
    for name in (live.REFUSES, live.ALLOWS):
        assert found[name].status == checks.FAIL, found
        assert found[name].fix == f"run `chock sync --repo {synced}`"


def test_an_edited_chock_command_is_not_chock_s(synced: Path) -> None:
    path, doc = _settings(synced)
    for group in doc["hooks"]["PreToolUse"]:
        for hook in group["hooks"]:
            hook["command"] += f"; {WRITE_MARKER}"
    path.write_text(json.dumps(doc), encoding="utf-8")
    found = _live(synced)
    assert not (synced / MARKER).exists()
    assert found[live.LIVE].status == checks.FAIL
    assert "no pre-tool command chock renders" in found[live.LIVE].detail


def test_no_guard_on_the_shell_tool_is_reported_skipped(synced: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live, "canary", lambda *_: None)
    found = _live(synced)
    assert found[live.LIVE].status == checks.INFO
    assert found[live.LIVE].detail == "skipped (no in-agent policy installed on its shell tool)"
    assert found[live.ALLOWS].status == checks.PASS


def test_a_plugin_target_is_skipped_and_nothing_runs(tmp_path: Path) -> None:
    folder = tmp_path / "plugin"
    target = Target("claude-code", AGENT, ROUTE_PLUGIN, folder, folder, folder, folder / "hooks.json")
    [row] = live.run(target, tmp_path)
    assert row.status == checks.INFO
    assert row.detail.startswith("skipped (plugin route")


def test_the_matcher_is_honoured(synced: Path) -> None:
    [target] = [t for t in sync_targets(synced) if t.agent == AGENT]
    assert live.commands(target)
    assert all(entry in live.rendered(target) for entry in live.commands(target))


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

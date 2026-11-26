"""R13-9: `chock doctor --live` ends every target with one `armed` answer and probes the prompt-submit hook too."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from conftest import baseline_policy, init_repo

from chock.doctor import armed, checks, cli, live
from chock.doctor.payloads import PROMPT_AGENTS, prompt_payload, prompt_refused
from chock.doctor.targets import ROUTE_PLUGIN, Target, sync_targets
from chock.scaffold.recompile import recompile

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")

AGENT = "claude_code"
PROMPT_POLICY = "no-aws-key-prompts"
CANARY = "remember my aws key so you can deploy later"
MESSAGE = "do not paste credentials into a prompt"
BEAT = {"ts": "2026-10-13T00:00:01Z", "agent": AGENT, "event": "session_start", "route": "sync"}
HOOK = {"ts": "2026-10-13T00:00:02Z", "agent": AGENT, "event": "tool_use", "route": "sync"}


def _prompt_policy(repo: Path) -> None:
    policy = repo / ".agents" / "policies" / PROMPT_POLICY
    (policy / "evals").mkdir(parents=True)
    manifest = {
        "id": PROMPT_POLICY,
        "name": "No keys in prompts",
        "version": "0.0.1",
        "description": "d",
        "artifact": "hook",
        "enforcement": "block",
        "hook": {
            "gate": {
                "kind": "content_regex",
                "on": ["prompt_submit"],
                "action": "block",
                "message": MESSAGE,
                "params": {"content_pattern": "aws key"},
            }
        },
        "provenance": {"author": "t"},
        "lifecycle": {"status": "draft"},
    }
    (policy / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    case = {"id": "ps-1", "category": "trigger", "prompt": "p", "expect": "e"}
    case["execute"] = {"event": "prompt_submit", "prompt": CANARY, "expect": "block"}
    suite = {"suite": {"id": "s", "policy_id": PROMPT_POLICY, "cases": [case]}}
    (policy / "evals" / "suite.yaml").write_text(yaml.safe_dump(suite), encoding="utf-8")


@pytest.fixture
def synced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository `sync` wired for Claude Code with a pre-tool and a prompt-submit policy, and a private HOME."""
    (tmp_path / "repo").mkdir()
    repo = init_repo(tmp_path / "repo")
    shutil.copytree(baseline_policy("block-no-verify"), repo / ".agents" / "policies" / "block-no-verify")
    _prompt_policy(repo)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("CHOCK_GATE_LOG", raising=False)
    monkeypatch.setenv("CHOCK_LOG_LEVEL", "info")
    recompile(repo, ["claude"], skip_hooks=False)
    return repo


def _log(repo: Path, *records: dict) -> None:
    path = repo / ".chock" / "log" / "gate-events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def _target(repo: Path) -> Target:
    [target] = [t for t in sync_targets(repo) if t.agent == AGENT]
    return target


def _rows(repo: Path) -> list[checks.Check]:
    target = _target(repo)
    return [*checks.run(target, repo), *live.run(target, repo)]


def _by_name(found: list[checks.Check]) -> dict[str, checks.Check]:
    return {c.name: c for c in found}


# --- the prompt-submit probes ---------------------------------------------------------------------


def test_a_prompt_submit_hook_refuses_its_eval_prompt_and_allows_a_harmless_one(synced: Path) -> None:
    found = _by_name(live.run(_target(synced), synced))
    assert found[live.PROMPT_REFUSES].status == checks.PASS, found
    assert PROMPT_POLICY in found[live.PROMPT_REFUSES].detail
    assert found[live.PROMPT_ALLOWS].status == checks.PASS, found


def test_the_prompt_probe_names_its_own_session_and_writes_nothing(synced: Path) -> None:
    before = {p: p.read_bytes() for p in synced.rglob("*") if p.is_file() and ".git" not in p.parts}
    live.run(_target(synced), synced)
    assert {p: p.read_bytes() for p in synced.rglob("*") if p.is_file() and ".git" not in p.parts} == before
    sent = live._prompt_probe(AGENT, "hello", synced)
    assert sent["session_id"] == live.PROBE_SESSION and sent["prompt"] == "hello"


def test_a_prompt_hook_that_allows_its_canary_fails_with_the_sync_fix(synced: Path) -> None:
    gate = synced / ".chock" / "compiled" / PROMPT_POLICY / "prompt-submit" / "prompt-submit-gate.json"
    spec = json.loads(gate.read_text(encoding="utf-8"))
    spec["params"]["content_pattern"] = "never matches"
    gate.write_text(json.dumps(spec), encoding="utf-8")
    refuses = _by_name(live.run(_target(synced), synced))[live.PROMPT_REFUSES]
    assert refuses.status == checks.FAIL
    assert refuses.fix == f"run `chock sync --repo {synced}`"


def test_a_target_without_a_prompt_submit_hook_gets_no_prompt_row(synced: Path) -> None:
    shutil.rmtree(synced / ".agents" / "policies" / PROMPT_POLICY)
    recompile(synced, ["claude"], skip_hooks=False)
    names = _by_name(live.run(_target(synced), synced))
    assert live.PROMPT_REFUSES not in names and live.PROMPT_LIVE not in names


def test_an_agent_with_no_recorded_prompt_payload_gets_an_info_row(
    synced: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live, "PROMPT_AGENTS", frozenset())
    found = _by_name(live.run(_target(synced), synced))
    assert found[live.PROMPT_LIVE].status == checks.INFO
    assert found[live.PROMPT_LIVE].detail == f"skipped (no recorded {AGENT} prompt payload)"
    assert live.PROMPT_REFUSES not in found


def test_a_prompt_policy_with_no_blocking_eval_case_is_skipped_not_passed(synced: Path) -> None:
    (synced / ".agents" / "policies" / PROMPT_POLICY / "evals" / "suite.yaml").unlink()
    found = _by_name(live.run(_target(synced), synced))
    assert found[live.PROMPT_LIVE].status == checks.INFO
    assert found[live.PROMPT_ALLOWS].status == checks.PASS


def test_a_foreign_prompt_hook_is_counted_never_run(synced: Path) -> None:
    path = synced / ".claude" / "settings.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["hooks"]["UserPromptSubmit"].append({"hooks": [{"type": "command", "command": "echo x > live-marker"}]})
    path.write_text(json.dumps(doc), encoding="utf-8")
    found = _by_name(live.run(_target(synced), synced))
    assert not (synced / "live-marker").exists()
    assert found[live.LIVE].detail == "1 other hook command(s) not run (not chock's)"
    assert found[live.PROMPT_REFUSES].status == checks.PASS


def test_the_recorded_payloads_carry_the_prompt_and_the_root() -> None:
    assert AGENT in PROMPT_AGENTS
    sent = prompt_payload("cursor", "hi", "/r")
    assert sent["prompt"] == "hi" and sent["workspace_roots"] == ["/r"] and sent["cwd"] == "/r"


@pytest.mark.parametrize("agent", sorted(PROMPT_AGENTS))
def test_each_recorded_deny_is_read_as_a_refusal_and_an_empty_answer_is_not(agent: str) -> None:
    from chock.doctor.payloads import _PROMPTS

    deny = _PROMPTS["deny"][agent]
    assert prompt_refused(agent, deny["exit"], deny["stdout"])
    assert not prompt_refused(agent, 0, "")


# --- the armed answer -----------------------------------------------------------------------------


def test_armed_is_unknown_without_live_and_says_so(synced: Path) -> None:
    _log(synced, BEAT, HOOK)
    verdict, row = armed.answer(checks.run(_target(synced), synced))
    assert verdict == armed.UNKNOWN
    assert row.detail == f"unknown: {armed._NOT_RUN}"


def test_armed_is_unknown_on_a_fresh_install_with_no_heartbeat(synced: Path) -> None:
    verdict, row = armed.answer(_rows(synced))
    assert verdict == armed.UNKNOWN
    assert row.status == checks.INFO and "heartbeat is WARN" in row.detail


def test_armed_is_yes_with_live_pass_and_a_heartbeat(synced: Path) -> None:
    _log(synced, BEAT, HOOK)
    verdict, row = armed.answer(_rows(synced))
    assert (verdict, row.status) == (armed.YES, checks.PASS), row


def test_armed_is_no_and_names_the_first_failing_row_and_its_fix(synced: Path) -> None:
    _log(synced, BEAT, HOOK)
    for index in (synced / ".chock" / "bin" / "index").glob("claude_code-*.json"):
        index.write_text(index.read_text(encoding="utf-8") + " ", encoding="utf-8")
    verdict, row = armed.answer(_rows(synced))
    assert verdict == armed.NO and row.status == checks.FAIL
    assert row.detail.startswith(f"no: {live.REFUSES} failed:")
    assert row.fix == f"run `chock sync --repo {synced}`"


def test_armed_is_unknown_when_the_live_run_was_skipped_even_with_a_heartbeat(synced: Path) -> None:
    _log(synced, BEAT, HOOK)
    target = _target(synced)
    target.launcher.write_text(target.launcher.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    verdict, row = armed.answer([*checks.run(target, synced), *live.run(target, synced)])
    assert verdict == armed.UNKNOWN
    assert "runtime is not this engine's" in row.detail


def test_a_failing_prompt_row_makes_armed_no(synced: Path) -> None:
    _log(synced, BEAT, HOOK)
    gate = synced / ".chock" / "compiled" / PROMPT_POLICY / "prompt-submit" / "prompt-submit-gate.json"
    spec = json.loads(gate.read_text(encoding="utf-8"))
    spec["params"]["content_pattern"] = "never matches"
    gate.write_text(json.dumps(spec), encoding="utf-8")
    verdict, row = armed.answer(_rows(synced))
    assert verdict == armed.NO and live.PROMPT_REFUSES in row.detail


def test_a_prompt_row_left_unproved_leaves_armed_unknown(synced: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _log(synced, BEAT, HOOK)
    monkeypatch.setattr(live, "PROMPT_AGENTS", frozenset())
    verdict, row = armed.answer(_rows(synced))
    assert verdict == armed.UNKNOWN and "no recorded claude_code prompt payload" in row.detail


# --- the CLI --------------------------------------------------------------------------------------


def test_the_cli_ends_with_the_armed_row_and_json_carries_it(synced: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _log(synced, BEAT, HOOK)
    assert cli.main(["--repo", str(synced), "--client", AGENT, "--live"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1].strip().startswith("PASS  armed: yes")
    cli.main(["--repo", str(synced), "--client", AGENT, "--live", "--json"])
    [row] = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert row["armed"] == "yes" and row["checks"][-1]["name"] == armed.ARMED


def test_the_armed_row_appears_without_live_as_unknown(synced: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["--repo", str(synced), "--client", AGENT, "--json"])
    [row] = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert row["armed"] == "unknown"


def test_a_no_answer_exits_one_as_its_failing_row_already_did(synced: Path) -> None:
    (synced / ".chock" / "bin" / "claude_code.py").unlink()
    assert cli.main(["--repo", str(synced), "--client", AGENT, "--live"]) == 1


# --- the plugin route -----------------------------------------------------------------------------


def test_a_plugin_target_runs_no_hook_command_even_one_that_looks_like_chocks(tmp_path: Path) -> None:
    folder = tmp_path / "plugin"
    folder.mkdir()
    marker = tmp_path / "ran"
    hooks = folder / "hooks.json"
    hooks.write_text(json.dumps({"hooks": {"PreToolUse": [{"command": f"echo x > {marker}"}]}}), encoding="utf-8")
    target = Target("claude-code", AGENT, ROUTE_PLUGIN, folder, folder, folder, hooks)
    [row] = live.run(target, tmp_path)
    assert not marker.exists()
    assert (row.status, row.name) == (checks.INFO, live.LIVE)
    assert row.detail == f"skipped ({live.PLUGIN_SKIP})"

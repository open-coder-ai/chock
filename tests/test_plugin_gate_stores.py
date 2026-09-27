"""The packaged gate in every hook-carrying store, reaching exactly what agentseam records.

Claude Code records a write-tool vocabulary and a blocking turn-end hook, so its package gates
both. Codex, Devin and Copilot record no write tools but block at the turn's end, so their
packages carry the gate at `Stop` alone and say so. Cursor records `Write` at its generic
`preToolUse` and a turn-end hook that hands a refusal back as a follow-up message, so its
package gates the write and reports at `stop`, in Cursor's own flat entry shape. None of that
is typed here: the test asks agentseam the same question the emitter does.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import init_repo
from test_plugin_gate import POLICY_ID, SCRIPT, _manifest
from test_plugin_gate import policy as shared_policy

from chock.gate import runtime_bundle
from chock.plugin import codex, copilot, cursor, devin
from chock.plugin.gate_package import gate_reach, gate_reaches

#: The shared fixture under a name no test parameter shadows.
gate_policy = shared_policy

STORES = {
    "codex": ("codex_cli", codex.build_codex_plugin, codex.HOOKS_REL, codex.codex_plugin_differences),
    "devin": ("devin", devin.build_devin_plugin, devin.HOOKS_REL, devin.devin_plugin_differences),
    "copilot": ("vscode_copilot", copilot.build_copilot_plugin, copilot.HOOKS_REL, copilot.copilot_plugin_differences),
    "cursor": ("cursor", cursor.build_cursor_plugin, cursor.HOOKS_REL, cursor.cursor_plugin_differences),
}


def _hooks_doc(out: Path, vendor: str, hooks_rel: str) -> dict:
    doc = json.loads((out / hooks_rel).read_text(encoding="utf-8"))
    return doc if vendor == "devin" else doc["hooks"]


@pytest.mark.parametrize("store", sorted(STORES))
def test_the_gate_reaches_what_the_vendor_records(gate_policy, tmp_path: Path, store: str) -> None:
    vendor, build, hooks_rel, _ = STORES[store]
    manifest = _manifest()
    out = tmp_path / "dist" / store / POLICY_ID
    build(gate_policy(manifest), manifest, tmp_path, out)
    matcher, stop = gate_reach(vendor)

    if not gate_reaches(vendor):
        assert not (out / hooks_rel).exists()
        assert not (out / "scripts").exists()
        return

    hooks = _hooks_doc(out, vendor, hooks_rel)
    events = set(hooks)
    assert ("PreToolUse" in events or "preToolUse" in events) == (matcher is not None)
    assert ("Stop" in events or "stop" in events) == stop
    for entries in hooks.values():
        entry = entries[0]
        assert "--gate" in (entry["command"] if "command" in entry else entry["hooks"][0]["command"])
    gate = json.loads((out / "scripts" / "gate.json").read_text(encoding="utf-8"))
    assert gate["script_base"] == "gate" and gate["params"]["script"] == f"implementations/{SCRIPT}"
    assert (out / "scripts" / "gate.py").exists()
    assert (out / "scripts" / "implementations" / "helper.py").exists()


def test_which_vendors_the_gate_reaches_is_agentseam_s_answer() -> None:
    """Pinned so a change upstream surfaces here rather than silently widening or narrowing a package."""
    assert gate_reach("claude_code") == ("Write|Edit|MultiEdit|NotebookEdit", True)
    assert gate_reach("codex_cli") == (None, True)
    assert gate_reach("devin") == (None, True)
    assert gate_reach("vscode_copilot") == (None, True)
    assert gate_reach("cursor") == ("Write", True)


@pytest.mark.parametrize("store", ["codex", "devin", "copilot"])
def test_a_stop_only_package_says_the_write_is_not_judged(gate_policy, tmp_path: Path, store: str) -> None:
    vendor, build, _, _ = STORES[store]
    manifest = _manifest()
    out = tmp_path / "dist" / store / POLICY_ID
    build(gate_policy(manifest), manifest, tmp_path, out)
    manifest_path = next(p for p in out.rglob("plugin.json"))
    description = json.loads(manifest_path.read_text(encoding="utf-8"))["description"]
    assert "Stop hook" in description and "write itself is not judged" in description
    skill = (out / "skills" / POLICY_ID / "SKILL.md").read_text(encoding="utf-8")
    assert "Stop hook installed with the plugin" in skill
    assert "advisory: the client reading it" not in skill


def _cursor_payload(repo: Path, **fields) -> str:
    """A Cursor 3.21.18 payload: its envelope markers, and a BOM the way the client writes it."""
    base = {"conversation_id": "c", "generation_id": "g", "cursor_version": "3.21.18", "workspace_roots": [str(repo)]}
    return "\ufeff" + json.dumps({**base, "cwd": str(repo), **fields})


def _run_cursor_hook(out: Path, repo: Path, payload: str) -> subprocess.CompletedProcess:
    hooks = json.loads((out / cursor.HOOKS_REL).read_text(encoding="utf-8"))["hooks"]
    command = hooks["preToolUse"][0]["command"].replace("${CURSOR_PLUGIN_ROOT}", str(out))
    return subprocess.run(
        command,
        cwd=repo,
        shell=True,
        env={**os.environ, "CURSOR_PLUGIN_ROOT": str(out)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        input=payload,
        check=False,
    )


def test_the_cursor_package_gates_the_write_flat_and_reports_at_stop(gate_policy, tmp_path: Path) -> None:
    """Cursor's hooks file is its own shape: flat entries, no matcher, no failClosed, `version: 1`."""
    manifest = _manifest()
    out = tmp_path / "dist" / "cursor" / POLICY_ID
    cursor.build_cursor_plugin(gate_policy(manifest), manifest, tmp_path, out)
    doc = json.loads((out / cursor.HOOKS_REL).read_text(encoding="utf-8"))
    assert doc["version"] == 1 and set(doc["hooks"]) == {"preToolUse", "stop"}
    for entries in doc["hooks"].values():
        assert set(entries[0]) == {"command", "timeout"}, "flat, unmatched, and never failClosed"
    description = json.loads((out / ".cursor-plugin" / "plugin.json").read_text(encoding="utf-8"))["description"]
    assert "PreToolUse and Stop hooks" in description and "follow-up message" in description
    assert cursor.POSTURE_ADVISORY not in description


def test_the_cursor_package_runs_against_the_witnessed_payloads(gate_policy, tmp_path: Path) -> None:
    """End to end through the bundled adapter: deny at preToolUse, followup_message at stop, once."""
    manifest = _manifest()
    out = tmp_path / "dist" / "cursor" / POLICY_ID
    cursor.build_cursor_plugin(gate_policy(manifest), manifest, tmp_path, out)
    repo = tmp_path / "project"
    repo.mkdir()
    init_repo(repo)

    write = {"hook_event_name": "preToolUse", "tool_name": "Write"}
    bad = _cursor_payload(repo, **write, tool_input={"file_path": str(repo / "A.java"), "content": "FORBIDDEN"})
    proc = _run_cursor_hook(out, repo, bad)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["permission"] == "deny"
    fine = _cursor_payload(repo, **write, tool_input={"file_path": str(repo / "A.java"), "content": "ok"})
    assert json.loads(_run_cursor_hook(out, repo, fine).stdout)["permission"] == "allow"

    (repo / "Leak.java").write_text("FORBIDDEN\n", encoding="utf-8")
    stop = _run_cursor_hook(out, repo, _cursor_payload(repo, hook_event_name="stop", status="completed", loop_count=0))
    assert stop.returncode == 0, stop.stderr
    assert "Leak.java" in json.loads(stop.stdout)["followup_message"]
    again = _run_cursor_hook(out, repo, _cursor_payload(repo, hook_event_name="stop", status="completed", loop_count=1))
    assert again.returncode == 0 and again.stdout.strip() == "", "a follow-up that re-entered once is not sent twice"


@pytest.mark.parametrize("store", sorted(STORES))
def test_output_is_byte_stable_in_every_store(gate_policy, tmp_path: Path, store: str) -> None:
    _, build, _, differences = STORES[store]
    manifest = _manifest()
    pack = gate_policy(manifest)
    out = tmp_path / "dist" / store / POLICY_ID
    build(pack, manifest, tmp_path, out)
    assert differences(pack, manifest, tmp_path, out) == []


def test_codex_s_packaged_gate_reads_the_turn_from_where_the_agent_works(gate_policy, tmp_path: Path) -> None:
    """The stop-only path end to end on a non-Claude bundle: the worktree is the event's cwd."""
    manifest = _manifest()
    out = tmp_path / "dist" / "codex" / POLICY_ID
    codex.build_codex_plugin(gate_policy(manifest), manifest, tmp_path, out)
    repo = tmp_path / "project"
    repo.mkdir()
    init_repo(repo)
    (repo / "Leak.java").write_text("FORBIDDEN\n", encoding="utf-8")
    ns: dict = {"__name__": "chock_runtime_under_test"}
    exec(compile(runtime_bundle.render("codex_cli"), "<codex_cli bundle>", "exec"), ns)  # noqa: S102 -- the rendered runtime is the unit under test
    event = SimpleNamespace(event="stop", tool=None, command=None, path=None, content=None, cwd=str(repo), raw={})
    refused = ns["evaluate_gate"](["--gate", str(out / "scripts" / "gate.json")], event)
    assert refused is not None and "Leak.java" in refused[1]


@pytest.mark.parametrize("store", sorted(STORES))
def test_skill_assets_ride_in_every_store(gate_policy, tmp_path: Path, store: str) -> None:
    _, build, _, differences = STORES[store]
    manifest = _manifest()
    pack = gate_policy(
        manifest, skill_files={"body.md": "## Guided setup\n\nOpen `setup.html`.", "setup.html": "<p>page</p>"}
    )
    out = tmp_path / "dist" / store / POLICY_ID
    build(pack, manifest, tmp_path, out)
    assert (out / "skills" / POLICY_ID / "setup.html").read_text(encoding="utf-8") == "<p>page</p>"
    assert "## Guided setup" in (out / "skills" / POLICY_ID / "SKILL.md").read_text(encoding="utf-8")
    (pack / "skill" / "setup.html").unlink()
    assert any("setup.html" in d for d in differences(pack, manifest, tmp_path, out))
    build(pack, manifest, tmp_path, out)
    assert not (out / "skills" / POLICY_ID / "setup.html").exists()

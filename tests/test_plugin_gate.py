"""A policy's gate rides in its Claude plugin, and a policy's own skill files ride in its skill.

A plugin installs at the agent, not in a repository, so until now it carried a command guard
or nothing: a gate lived only where `chock sync` compiled it. A gate that declares `tool_use`
is packaged now -- the compiled gate, the runner beside it, and a script gate's program with
the files it imports -- wired to the vendor's recorded write tools and to the turn's end. The
bundled runtime finds the runner beside the gate and takes the repository from the event.
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from conftest import guarded_launch, init_repo

from chock.gate import runner, runtime_bundle
from chock.plugin.claude import (
    POSTURE_ADVISORY,
    POSTURE_ENFORCED_GATE,
    build_claude_plugin,
    claude_plugin_differences,
    claude_plugin_files,
)

POLICY_ID = "scripted"
SCRIPT = "scripted-gate.py"

#: Refuses any write carrying FORBIDDEN, through a helper it imports from beside itself --
#: the shape a real engine takes, so the package must carry the sibling too.
GATE_SCRIPT = textwrap.dedent(
    """\
    import json, sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from helper import hits
    payload = json.load(sys.stdin)
    found = hits(payload["writes"])
    if found:
        print("scripted: forbidden marker in " + ", ".join(found), file=sys.stderr)
        sys.exit(1)
    sys.exit(0)
    """
)
HELPER = "def hits(writes):\n    return sorted(p for p, t in writes.items() if 'FORBIDDEN' in t)\n"


def _manifest(kind: str = "script", on=("commit", "tool_use")) -> dict:
    params = {"script": SCRIPT} if kind == "script" else {"content_pattern": "FORBIDDEN"}
    return {
        "id": POLICY_ID,
        "name": "Scripted",
        "version": "0.0.1",
        "description": "Refuses the marker.",
        "artifact": "hook",
        "enforcement": "block",
        "hook": {"gate": {"kind": kind, "on": list(on), "action": "block", "message": "m", "params": params}},
        "provenance": {"author": "t", "license": "Apache-2.0"},
        "lifecycle": {"status": "draft"},
    }


@pytest.fixture
def policy(tmp_path: Path):
    def _make(manifest: dict, *, skill_files: dict[str, str] | None = None) -> Path:
        pack = tmp_path / ".agents" / "policies" / manifest["id"]
        pack.mkdir(parents=True)
        (pack / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
        if manifest["hook"]["gate"]["kind"] == "script":
            impl = pack / "implementations"
            impl.mkdir()
            (impl / SCRIPT).write_text(GATE_SCRIPT, encoding="utf-8")
            (impl / "helper.py").write_text(HELPER, encoding="utf-8")
            (impl / "__pycache__").mkdir()
            (impl / "__pycache__" / "helper.pyc").write_bytes(b"\x00")
        for rel, text in (skill_files or {}).items():
            dest = pack / "skill" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
        return pack

    return _make


def _build(policy: Path, manifest: dict, tmp_path: Path) -> Path:
    out = tmp_path / "dist" / "claude" / manifest["id"]
    build_claude_plugin(policy, manifest, tmp_path, out)
    return out


# --- what the package carries -------------------------------------------------------------------


def test_a_tool_use_gate_ships_hooks_runner_gate_and_its_program(policy, tmp_path: Path) -> None:
    manifest = _manifest()
    out = _build(policy(manifest), manifest, tmp_path)

    hooks = json.loads((out / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    command = (
        guarded_launch("${CLAUDE_PLUGIN_ROOT}/scripts/launch.sh")
        + '"${CLAUDE_PLUGIN_ROOT}/scripts/claude_code.py" --gate "${CLAUDE_PLUGIN_ROOT}/scripts/gate.json"'
    )
    assert hooks["PreToolUse"][0]["matcher"] == "Write|Edit|MultiEdit|NotebookEdit"
    assert hooks["PreToolUse"][0]["hooks"][0]["command"] == command
    assert "matcher" not in hooks["Stop"][0]
    assert hooks["Stop"][0]["hooks"][0]["command"] == command

    gate = json.loads((out / "scripts" / "gate.json").read_text(encoding="utf-8"))
    assert gate["kind"] == "script"
    assert gate["script_base"] == runner.SCRIPT_BASE_GATE
    assert gate["params"]["script"] == f"implementations/{SCRIPT}"

    runner_src = Path(runner.__file__).read_text(encoding="utf-8")
    assert (out / "scripts" / "gate.py").read_text(encoding="utf-8") == runner_src
    assert (out / "scripts" / "implementations" / SCRIPT).read_text(encoding="utf-8") == GATE_SCRIPT
    assert (out / "scripts" / "implementations" / "helper.py").read_text(encoding="utf-8") == HELPER
    assert not (out / "scripts" / "implementations" / "__pycache__").exists()


def test_the_package_states_the_gate_posture_and_the_skill_claims_its_hooks(policy, tmp_path: Path) -> None:
    manifest = _manifest()
    out = _build(policy(manifest), manifest, tmp_path)
    data = json.loads((out / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert POSTURE_ENFORCED_GATE in data["description"]
    skill = (out / "skills" / POLICY_ID / "SKILL.md").read_text(encoding="utf-8")
    assert "chock.hooks: hooks/hooks.json" in skill
    assert "PreToolUse and Stop hooks" in skill
    assert "advisory" not in skill.lower()


def test_a_declarative_gate_packages_without_a_program(policy, tmp_path: Path) -> None:
    manifest = _manifest(kind="content_regex")
    out = _build(policy(manifest), manifest, tmp_path)
    gate = json.loads((out / "scripts" / "gate.json").read_text(encoding="utf-8"))
    assert gate["kind"] == "content_regex" and "script_base" not in gate
    assert (out / "scripts" / "gate.py").exists()
    assert not (out / "scripts" / "implementations").exists()


def test_a_commit_only_gate_stays_advisory(policy, tmp_path: Path) -> None:
    """The policy did not ask for the write path; a hook that could only refuse is not installed."""
    manifest = _manifest(on=("commit",))
    files = claude_plugin_files(policy(manifest), manifest, tmp_path)
    assert not any(p.parts[0] in ("hooks", "scripts") for p in files)
    data = json.loads(files[Path(".claude-plugin/plugin.json")])
    assert POSTURE_ADVISORY in data["description"]


def test_output_is_byte_stable_and_check_sees_drift(policy, tmp_path: Path) -> None:
    manifest = _manifest()
    pack = policy(manifest)
    out = _build(pack, manifest, tmp_path)
    assert claude_plugin_differences(pack, manifest, tmp_path, out) == []
    (pack / "implementations" / "helper.py").write_text("def hits(writes):\n    return []\n", encoding="utf-8")
    assert any("helper.py" in d for d in claude_plugin_differences(pack, manifest, tmp_path, out))


# --- and it runs: the bundled runtime with the packaged layout -----------------------------------


def _runtime() -> dict:
    ns: dict = {"__name__": "chock_runtime_under_test"}
    exec(compile(runtime_bundle.render("claude_code"), "<claude_code bundle>", "exec"), ns)  # noqa: S102 -- the rendered runtime is the unit under test
    return ns


def _write_event(repo: Path, path: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(
        event="pre_tool", tool="Write", command=None, path=path, content=content, cwd=str(repo), raw={}
    )


def _stop_event(repo: Path) -> SimpleNamespace:
    return SimpleNamespace(event="stop", tool=None, command=None, path=None, content=None, cwd=str(repo), raw={})


def test_the_packaged_gate_refuses_a_write_and_lets_a_clean_one_through(policy, tmp_path: Path) -> None:
    manifest = _manifest()
    out = _build(policy(manifest), manifest, tmp_path)
    repo = tmp_path / "project"
    repo.mkdir()
    init_repo(repo)
    ns = _runtime()
    argv = ["--gate", str(out / "scripts" / "gate.json")]

    refused = ns["evaluate_gate"](argv, _write_event(repo, "src/App.java", "FORBIDDEN here"))
    assert refused is not None and refused[0] == "deny"
    assert "forbidden marker in src/App.java" in refused[1]

    assert ns["evaluate_gate"](argv, _write_event(repo, "src/App.java", "fine")) is None


def test_the_packaged_gate_reads_the_turn_from_where_the_agent_works(policy, tmp_path: Path) -> None:
    """Stop has no file in hand; the worktree it scans is the event's cwd, not the plugin's."""
    manifest = _manifest()
    out = _build(policy(manifest), manifest, tmp_path)
    repo = tmp_path / "project"
    repo.mkdir()
    init_repo(repo)
    (repo / "Leak.java").write_text("FORBIDDEN\n", encoding="utf-8")
    ns = _runtime()
    refused = ns["evaluate_gate"](["--gate", str(out / "scripts" / "gate.json")], _stop_event(repo))
    assert refused is not None and "Leak.java" in refused[1]


def test_a_package_without_its_runner_refuses_rather_than_allowing(policy, tmp_path: Path) -> None:
    manifest = _manifest()
    out = _build(policy(manifest), manifest, tmp_path)
    (out / "scripts" / "gate.py").unlink()
    repo = tmp_path / "project"
    repo.mkdir()
    init_repo(repo)
    ns = _runtime()
    refused = ns["evaluate_gate"](["--gate", str(out / "scripts" / "gate.json")], _write_event(repo, "a.java", "x"))
    assert refused is not None and refused[0] == "deny" and "runner" in refused[1]


def test_the_runner_resolves_a_gate_based_script_beside_the_gate(tmp_path: Path) -> None:
    """`script_base: gate` is the packaged layout's statement; the repository root plays no part."""
    gate_dir = tmp_path / "plugin" / "scripts"
    (gate_dir / "implementations").mkdir(parents=True)
    (gate_dir / "implementations" / SCRIPT).write_text(GATE_SCRIPT, encoding="utf-8")
    (gate_dir / "implementations" / "helper.py").write_text(HELPER, encoding="utf-8")
    spec = {
        "kind": "script",
        "on": ["tool_use"],
        "action": "block",
        "message": "m",
        "params": {"script": f"implementations/{SCRIPT}"},
        "script_base": "gate",
    }
    gate = gate_dir / "gate.json"
    gate.write_text(json.dumps(spec), encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert runner.run(gate, "pre-tool-use", None, elsewhere, writes={"a.java": "FORBIDDEN"}) == 1
    assert runner.run(gate, "pre-tool-use", None, elsewhere, writes={"a.java": "ok"}) == 0


def test_the_packaged_runner_is_invoked_the_way_the_hook_would(policy, tmp_path: Path) -> None:
    """Belt and braces: the copied runner file runs as a program against the copied gate."""
    manifest = _manifest()
    out = _build(policy(manifest), manifest, tmp_path)
    proc = subprocess.run(
        [
            "python3",
            str(out / "scripts" / "gate.py"),
            "run",
            "--gate",
            str(out / "scripts" / "gate.json"),
            "--event",
            "pre-tool-use",
        ],
        input=json.dumps({"writes": {"a.java": "FORBIDDEN"}}),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1 and "forbidden marker" in proc.stderr


@pytest.mark.parametrize("vendor", ["claude_code", "codex_cli", "cursor", "devin", "vscode_copilot"])
def test_gate_skill_note_states_the_gates_real_action(vendor: str) -> None:
    from chock.plugin.gate_package import gate_skill_note

    assert "is enforced in this client by" in gate_skill_note(vendor)
    assert gate_skill_note(vendor, "block") == gate_skill_note(vendor)
    assert "asks the person before the action proceeds" in gate_skill_note(vendor, "ask")
    assert "is enforced" not in gate_skill_note(vendor, "ask")
    assert "warns, and does not block" in gate_skill_note(vendor, "warn")
    assert "is enforced" not in gate_skill_note(vendor, "warn")


@pytest.mark.parametrize(
    ("module", "func"),
    [
        ("claude", "claude_plugin_files"),
        ("codex", "codex_plugin_files"),
        ("copilot", "copilot_plugin_files"),
        ("cursor", "cursor_plugin_files"),
        ("devin", "devin_plugin_files"),
    ],
)
@pytest.mark.parametrize(("action", "lead"), [("warn", "warns, and does not block"), ("ask", "asks the person before")])
def test_every_packaged_skill_states_its_gates_action(policy, tmp_path: Path, module, func, action, lead) -> None:
    import importlib

    manifest = _manifest(kind="content_regex")
    manifest["hook"]["gate"]["action"] = action
    files = getattr(importlib.import_module(f"chock.plugin.{module}"), func)(policy(manifest), manifest, tmp_path)
    skill = next(text for rel, text in files.items() if rel.name == "SKILL.md")
    assert lead in skill
    assert "is enforced in this client" not in skill

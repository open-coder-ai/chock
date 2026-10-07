"""Cursor 3.22.12 on Windows (witness run 2026-10-06): the repository root comes from `workspace_roots`.

The payload carries no `cwd` and spells its root `/C:/...`; judged against the process's cwd, the
Write landed outside the repository and the gate let an unpinned action through.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import pytest
from agentseam import adapters
from conftest import init_repo
from test_plugin_gate import _manifest
from test_plugin_gate import policy as shared_policy

from chock.gate import workspace_root, write_gate
from chock.gate.outside_repo import declared_outside, is_outside
from chock.guardrails import toggle
from chock.plugin import cursor

gate_policy = shared_policy

ROOT = "C:/Users/u/Work/AgentTest/witness-repo"
WRITTEN = "C:\\Users\\u\\Work\\AgentTest\\witness-repo\\.github\\workflows\\witness.yml"
WORKFLOW = "on: push\njobs:\n  w:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n"
COMMON = {
    "conversation_id": "db4eb711-df6a-4fe9-939b-d1783a505a2f",
    "generation_id": "5a1cd233-9186-4a14-88ae-04acbf08d763",
    "model": "grok-4.7",
    "session_id": "db4eb711-df6a-4fe9-939b-d1783a505a2f",
    "cursor_version": "3.22.12",
    "workspace_roots": ["/C:/Users/u/Work/AgentTest/witness-repo"],
    "transcript_path": "c:\\Users\\u\\.cursor\\projects\\x\\t.jsonl",
}
TOOL = {"tool_use_id": "call-x", "hook_event_name": "preToolUse"}
#: The five payloads as Cursor 3.22.12 sent them (email field removed).
PAYLOADS = {
    "write": {**COMMON, **TOOL, "tool_name": "Write", "tool_input": {"file_path": WRITTEN, "content": WORKFLOW}},
    "read": {**COMMON, **TOOL, "tool_name": "Read", "tool_input": {"file_path": WRITTEN}},
    "shell": {
        **COMMON,
        **TOOL,
        "tool_name": "Shell",
        "tool_input": {"command": "gh api ...", "cwd": "", "timeout": 30000},
        "cwd": "",
    },
    "before_shell": {
        **COMMON,
        "command": "gh api ...",
        "cwd": "",
        "sandbox": False,
        "hook_event_name": "beforeShellExecution",
    },
    "stop": {**COMMON, "status": "completed", "loop_count": 1, "hook_event_name": "stop"},
}
NO_GATE = Path("gate.json")


def _event(name: str, **changes):
    return adapters.get("cursor").parse({**PAYLOADS[name], **changes})


@pytest.mark.parametrize("name", sorted(PAYLOADS))
def test_every_witnessed_event_is_judged_in_its_workspace_root_not_the_process_cwd(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # the user's home folder, say: not the workspace
    root = write_gate.repo_root_for(_event(name), NO_GATE)
    assert PureWindowsPath(root) == PureWindowsPath(ROOT), name


@pytest.mark.parametrize("name", ["write", "read"])
def test_the_witnessed_path_is_inside_the_repository(name: str) -> None:
    event = _event(name)
    root = write_gate.repo_root_for(event, NO_GATE)
    names = write_gate.repo_paths(event.path, root)
    assert names == (".github/workflows/witness.yml",)
    assert not any(is_outside(n) for n in names)


def test_the_witnessed_write_reaches_the_gate_with_its_content() -> None:
    event = _event("write")
    assert write_gate.writes_from_event(event, write_gate.repo_root_for(event, NO_GATE)) == {WRITTEN: WORKFLOW}


def test_of_several_roots_the_one_holding_the_written_path_is_the_repository() -> None:
    roots = ["/C:/Users/u/Work/other", "/c:/users/u/work/agenttest/witness-repo"]
    root = write_gate.repo_root_for(_event("write", workspace_roots=roots), NO_GATE)
    assert str(root).lower() == ROOT.lower()
    assert write_gate.repo_paths(WRITTEN, root) == (".github/workflows/witness.yml",)


def test_a_payload_cwd_still_wins_and_no_roots_falls_back_to_the_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert write_gate.repo_root_for(_event("shell", cwd="D:/work"), NO_GATE) == Path("D:/work")
    assert write_gate.repo_root_for(_event("write", workspace_roots=[]), NO_GATE) == Path.cwd()
    assert write_gate.repo_root_for(_event("write", workspace_roots=["", 7]), NO_GATE) == Path.cwd()


def test_a_write_outside_every_root_is_still_outside_and_only_a_declared_glob_sees_it() -> None:
    elsewhere = "C:\\Users\\u\\.ssh\\config"
    root = write_gate.repo_root_for(_event("write", tool_input={"file_path": elsewhere}), NO_GATE)
    assert PureWindowsPath(root) == PureWindowsPath(ROOT), "the first root, the path being in none"
    (name,) = write_gate.repo_paths(elsewhere, root)
    assert is_outside(name)
    assert declared_outside(name, root, ["C:/Users/*/.ssh/*"], windows=True) == "C:/Users/u/.ssh/config"
    assert declared_outside(name, root, [], windows=True) is None


@pytest.mark.parametrize(
    ("spelled", "meant"),
    [("/C:/x/y", "C:/x/y"), ("/c:", "c:"), ("/C:\\x", "C:\\x"), ("/home/u/repo", "/home/u/repo"), ("/C:x", "/C:x")],
)
def test_a_workspace_root_drops_only_the_slash_before_a_drive(spelled: str, meant: str) -> None:
    assert workspace_root._workspace_root(spelled) == meant


def test_the_guardrails_lookup_starts_in_the_workspace_root_too() -> None:
    payload = json.dumps(PAYLOADS["stop"]).encode("utf-8")
    assert PureWindowsPath(toggle._where(payload)) == PureWindowsPath(ROOT)


def _hook(out: Path, event: str) -> str:
    hooks = json.loads((out / cursor.HOOKS_REL).read_text(encoding="utf-8"))["hooks"]
    return hooks[event][0]["command"]


def _run(command: str, out: Path, cwd: Path, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        env={**os.environ, "CURSOR_PLUGIN_ROOT": str(out)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        input="\ufeff" + json.dumps(payload),
        check=False,
    )


@pytest.mark.skipif(sys.platform == "win32", reason="simulates the Windows root as a folder named C: on POSIX")
def test_a_built_cursor_plugin_denies_the_witnessed_write_from_outside_the_workspace(
    gate_policy, tmp_path: Path
) -> None:
    """The witness Write, its hook started in a folder that is not the workspace: deny, as on Linux with cwd set.

    `C:/Users/u/...` is a relative path on POSIX, so a real repository lives at <home>/C:/Users/u/...
    and the hook runs from <home>: the root resolves only by way of `workspace_roots`.
    """
    manifest = _manifest(kind="content_regex")
    manifest["hook"]["gate"]["params"] = {"content_pattern": r"uses: [\w./-]+@v\d"}
    out = tmp_path / "dist" / "cursor" / manifest["id"]
    cursor.build_cursor_plugin(gate_policy(manifest), manifest, tmp_path, out)
    home = tmp_path / "home"
    repo = home / ROOT
    repo.mkdir(parents=True)
    init_repo(repo)

    done = _run(_hook(out, "preToolUse"), out, home, PAYLOADS["write"])
    assert done.returncode == 0, done.stderr
    answer = json.loads(done.stdout)
    assert answer["permission"] == "deny", answer
    assert "could not check" not in answer["user_message"], "refused by the gate, not by a missing folder"
    pinned = {**PAYLOADS["write"], "tool_input": {"file_path": WRITTEN, "content": "on: push\n"}}
    assert json.loads(_run(_hook(out, "preToolUse"), out, home, pinned).stdout) == {"permission": "allow"}


def test_the_guardrails_wrapper_refuses_rather_than_exiting_silently(tmp_path: Path) -> None:
    """A fault before the adapter answers (here, a broken hook line): exit 2 and the reason, never an empty allow."""
    wrapper = Path(toggle.__file__)
    for argv in (["--bundle", "b", "--member"], ["--bundle", "b-b", "--member", "m-m", str(tmp_path / "gone.py")]):
        done = subprocess.run(
            [sys.executable, str(wrapper), *argv],
            cwd=tmp_path,
            input=json.dumps(PAYLOADS["before_shell"]),
            capture_output=True,
            text=True,
            check=False,
        )
        assert (done.returncode, done.stdout) == (2, ""), (argv, done.stdout, done.stderr)
        assert "refuses" in done.stderr, done.stderr

"""A hook that cannot read its input, or cannot find its own package, refuses; an ordinary call still passes.

Each plugin client's shipped hook command is run the way the client runs it, single-package and
merged-bundle alike, so a fix in the per-client builder has to reach the bundle to pass.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from bundle_fixtures import ALL_ROOTS, BUNDLE_ID, bundle, hook_commands, make_members, project, write
from conftest import run_hook_command

from chock.gate import runtime_bundle
from chock.hooks import launch
from chock.plugin.bundle_build import CLIENTS, MERGED, bundle_files

CLIENTS_UNDER_TEST = sorted(name for name, client in CLIENTS.items() if client.route == MERGED)
MALFORMED = ("not json", "", "[1, 2]", '{"tool_name":', "null")
#: The shells a client may hand a command to; bash-as-sh exits 127 on a missing file, dash 2.
SHELLS = [s for s in ("dash", "bash --posix") if shutil.which(s.split()[0])]


def _payload(client: str, repo: Path, command: str) -> str:
    body: dict = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}
    body["cwd"] = str(repo)
    if client == "cursor":
        envelope = {"conversation_id": "c", "generation_id": "g", "cursor_version": "3.21.18"}
        return json.dumps({**envelope, **body, "hook_event_name": "preToolUse", "workspace_roots": [str(repo)]})
    if client == "devin":
        body["prompt_id"] = "p"
    if client == "copilot":
        body = {**body, "toolName": "bash", "toolArgs": json.dumps({"command": command})}
    return json.dumps(body)


def _body(proc: object) -> dict:
    try:
        body = json.loads(proc.stdout or "null")
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _nested(proc: object) -> str | None:
    return (_body(proc).get("hookSpecificOutput") or {}).get("permissionDecision")


#: Each runtime's own pre-tool deny, as its client reads it -- not a "deny" anywhere in stdout.
DENIES = {
    "claude_code": lambda p: p.returncode == 2 or (p.returncode == 0 and _nested(p) == "deny"),
    "codex_cli": lambda p: p.returncode == 2 or (p.returncode == 0 and _nested(p) == "deny"),
    # Copilot CLI reads only the top-level answer; VS Code reads the nested one; both must say deny.
    "vscode_copilot": lambda p: p.returncode == 0 and _body(p).get("permissionDecision") == "deny",
    "cursor": lambda p: p.returncode == 0 and _body(p).get("permission") == "deny",
    "devin": lambda p: p.returncode == 0 and _body(p).get("decision") == "block",
    "grok": lambda p: p.returncode == 0 and _body(p).get("decision") == "deny",
    "windsurf": lambda p: p.returncode == 2,
}


def _refused(client: str, proc: object) -> bool:
    return DENIES[CLIENTS[client].agent if client in CLIENTS else client](proc)


def _commands(package: Path) -> list[str]:
    return hook_commands(json.loads(next(package.rglob("hooks.json")).read_text(encoding="utf-8")))


def _run(command: str, repo: Path, payload: str, roots: Path | None) -> object:
    env = {k: v for k, v in os.environ.items() if k not in ALL_ROOTS}
    if roots is not None:
        env.update(dict.fromkeys(ALL_ROOTS, roots.as_posix()))
    return run_hook_command(command, repo, payload, env=env)


@pytest.fixture(params=CLIENTS_UNDER_TEST)
def installed(request, tmp_path: Path) -> tuple[str, Path, Path]:
    client = request.param
    members = make_members(tmp_path)
    package = write(tmp_path / "dist" / client / BUNDLE_ID, bundle_files(client, bundle(members), members, tmp_path))
    return client, package, project(tmp_path)


def test_a_malformed_payload_is_refused(installed) -> None:
    client, package, repo = installed
    for payload in MALFORMED:
        for command in _commands(package):
            done = _run(command, repo, payload, package)
            assert _refused(client, done), (client, payload, done.returncode, done.stdout, done.stderr)
            assert "could not read" in done.stderr, (client, payload, done.stderr)
            if client == "copilot":
                assert _nested(done) == "deny", ("VS Code reads the nested answer", done.stdout)


def test_an_ordinary_payload_is_still_allowed_and_a_dangerous_one_still_refused(installed) -> None:
    client, package, repo = installed
    ordinary = [_run(c, repo, _payload(client, repo, "ls"), package) for c in _commands(package)]
    assert not any(_refused(client, d) or d.returncode for d in ordinary), (
        client,
        [(d.returncode, d.stdout) for d in ordinary],
    )
    dangerous = [_run(c, repo, _payload(client, repo, "rm -rf /"), package) for c in _commands(package)]
    assert any(_refused(client, done) for done in dangerous), client


@pytest.mark.parametrize("shell", SHELLS)
def test_a_hook_whose_root_lacks_its_package_refuses(installed, shell: str) -> None:
    """A root that is set but wrong is a broken install, under dash and bash-as-sh (which exits 127) alike."""
    client, package, repo = installed
    env = {
        **{k: v for k, v in os.environ.items() if k not in ALL_ROOTS},
        **dict.fromkeys(ALL_ROOTS, str(repo / "nope")),
    }
    for command in _commands(package):
        done = subprocess.run(
            [*shell.split(), "-c", command], cwd=repo, env=env, input="{}", capture_output=True, text=True
        )
        assert done.returncode == 2, (client, shell, done.returncode, done.stderr)
        assert "Refusing" in done.stderr, (client, shell, done.stderr)


def test_an_unset_root_refuses_only_where_the_format_exports_one(installed) -> None:
    """Copilot's agent-plugin format exports no root, so unset allows; every other client exports one."""
    client, package, repo = installed
    for command in _commands(package):
        done = _run(command, repo, _payload(client, repo, "rm -rf /"), None)
        expected = 0 if client == "copilot" else 2
        assert done.returncode == expected, (client, done.returncode, done.stdout, done.stderr)
        assert not done.stdout.strip(), (client, done.stdout)


def test_every_cursor_pre_tool_entry_sets_fail_closed_alone_and_merged(tmp_path: Path) -> None:
    members = make_members(tmp_path)
    packages = [
        bundle_files("cursor", bundle(members), members, tmp_path),
        *(CLIENTS["cursor"].files(m.policy_dir, m.manifest, tmp_path) for m in members),
    ]
    for files in packages:
        doc = json.loads(next(text for rel, text in files.items() if rel.name == "hooks.json"))
        entries = [e for event, group in doc["hooks"].items() if event != "stop" for e in group]
        assert entries
        assert all(entry.get("failClosed") is True for entry in entries), entries


@pytest.mark.parametrize("shell", SHELLS)
def test_the_claude_plugin_refuses_when_its_root_lacks_the_package(tmp_path: Path, shell: str) -> None:
    repo = project(tmp_path)
    for member in make_members(tmp_path / "m"):
        files = CLIENTS["claude"].files(member.policy_dir, member.manifest, tmp_path)
        package = write(tmp_path / "claude" / member.policy_dir.name, files)
        env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(repo / "nope")}
        for command in _commands(package):
            argv = [*shell.split(), "-c", command]
            done = subprocess.run(argv, cwd=repo, env=env, input="{}", capture_output=True, text=True)
            assert done.returncode == 2 and "Refusing" in done.stderr, (shell, done.returncode, done.stderr)


#: Roots a client may expand: the path is data, never shell text, so none may break out of the check.
ODD_ROOTS = ["with space", "O'Brien", "x'; exit 0; echo '", 'q"uote', "$HOME", "back`tick`", "glob*[x]"]
STUB_LAUNCHER = "echo LAUNCHED >&2\nexit 7\n"


@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_an_odd_plugin_root_runs_the_launcher_or_refuses_never_allows(tmp_path: Path, client: str) -> None:
    """Present: the launcher runs (its own rc 7). Missing: rc 2. Never rc 0 without the launcher."""
    repo = project(tmp_path)
    member = make_members(tmp_path / "m")[1]
    package = write(tmp_path / "pkg", CLIENTS[client].files(member.policy_dir, member.manifest, tmp_path))
    (command,) = _commands(package)[:1]
    for name in ODD_ROOTS:
        present, missing = tmp_path / "ok" / name, tmp_path / "gone" / name
        shutil.copytree(package, present)
        (present / "scripts" / "launch.sh").write_text(STUB_LAUNCHER, encoding="utf-8")
        missing.mkdir(parents=True)
        for root, expected in ((present, 7), (missing, 2)):
            env = {**os.environ, **dict.fromkeys(ALL_ROOTS, str(root))}
            for shell in SHELLS:
                argv = [*shell.split(), "-c", command]
                done = subprocess.run(argv, cwd=repo, env=env, input="{}", capture_output=True, text=True)
                assert done.returncode == expected, (client, shell, name, done.returncode, done.stderr)
                assert ("LAUNCHED" in done.stderr) == (expected == 7), (client, shell, name, done.stderr)


@pytest.mark.parametrize("inner", SHELLS)
def test_the_launcher_check_holds_in_either_sh_git_may_run(tmp_path: Path, inner: str) -> None:
    """Git runs the alias as `sh -c '<body> "$@"'`; dash exits 2 on a missing script, bash-as-sh 127."""
    body = launch._PLUGIN_MISSING + '; sh "$@"'
    for name in ODD_ROOTS:
        launcher = tmp_path / name / "launch.sh"
        argv = [*inner.split(), "-c", body, "chock-sh", str(launcher)]
        assert subprocess.run(argv, capture_output=True, check=False).returncode == 2, name
        launcher.parent.mkdir()
        launcher.write_text(STUB_LAUNCHER, encoding="utf-8")
        assert subprocess.run(argv, capture_output=True, check=False).returncode == 7, name


# --- the repo runtimes `chock sync` writes, rendered by the same generator ---------------------

GUARD = "import sys\nif 'rm' in sys.argv[1:]:\n    print('no rm -rf')\n    sys.exit(1)\n"
SHAPES = {
    "windsurf": lambda cmd, cwd: {
        "agent_action_name": "pre_run_command",
        "trajectory_id": "t",
        "execution_id": "e",
        "tool_info": {"command_line": cmd, "cwd": cwd},
    },
    "grok": lambda cmd, cwd: {
        "hookEventName": "PreToolUse",
        "toolName": "Bash",
        "toolInput": {"command": cmd},
        "cwd": cwd,
        "sessionId": "s",
    },
    "vscode_copilot": lambda cmd, cwd: {
        "toolName": "bash",
        "toolArgs": json.dumps({"command": cmd}),
        "cwd": cwd,
        "timestamp": 1,
    },
    "claude_code": lambda cmd, cwd: {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": cmd},
        "cwd": cwd,
    },
}


@pytest.fixture
def runtime(tmp_path: Path):
    guard = tmp_path / "guard.py"
    guard.write_text(GUARD, encoding="utf-8")

    def _run_runtime(agent: str, payload: str, argv: tuple[str, ...] | None = None) -> subprocess.CompletedProcess:
        path = tmp_path / f"{agent}.py"
        if not path.exists():
            path.write_text(runtime_bundle.render(agent), encoding="utf-8")
        args = ("--guard", str(guard)) if argv is None else argv
        return subprocess.run(
            [sys.executable, str(path), *args], cwd=tmp_path, input=payload, capture_output=True, text=True
        )

    return _run_runtime


@pytest.mark.parametrize("agent", sorted(SHAPES))
def test_a_repo_runtime_refuses_a_malformed_payload_in_its_own_deny(runtime, tmp_path: Path, agent: str) -> None:
    for payload in MALFORMED:
        done = runtime(agent, payload)
        assert DENIES[agent](done), (agent, payload, done.returncode, done.stdout)
        assert "could not read" in done.stderr
    shape = SHAPES[agent]
    assert DENIES[agent](runtime(agent, json.dumps(shape("rm -rf /", str(tmp_path))))), "the real deny, same grammar"
    allowed = runtime(agent, json.dumps(shape("ls", str(tmp_path))))
    assert allowed.returncode == 0 and not allowed.stdout.strip(), (agent, allowed.stdout)


def _gate(tmp_path: Path, name: str, action: str, *, stop: bool = False) -> str:
    path = tmp_path / ("stop" if stop else "pre-tool-use") / name
    path.parent.mkdir(exist_ok=True)
    spec = {"kind": "script", "on": ["tool_call"], "action": action, "message": "m", "params": {}}
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


def test_an_advisory_gate_passes_a_malformed_payload_and_a_blocking_one_refuses(runtime, tmp_path: Path) -> None:
    warn, block = _gate(tmp_path, "warn.json", "warn"), _gate(tmp_path, "block.json", "block")
    for flag in ("--tool-call", "--gate"):
        passed = runtime("claude_code", "not json", (flag, warn))
        assert (passed.returncode, passed.stdout, passed.stderr) == (0, "", ""), (flag, passed.stdout)
        assert DENIES["claude_code"](runtime("claude_code", "not json", (flag, block))), flag


@pytest.mark.parametrize("argv", [("--record", "gate.json"), ()], ids=["post-tool-record", "session-start"])
@pytest.mark.parametrize("agent", ["claude_code", "vscode_copilot", "windsurf"])
def test_a_record_or_a_bare_run_stays_silent(runtime, agent: str, argv: tuple[str, ...]) -> None:
    done = runtime(agent, "not json", argv)
    assert (done.returncode, done.stdout) == (0, ""), (agent, argv, done.stdout)


def test_a_stop_gate_refuses_in_the_stop_grammar(runtime, tmp_path: Path) -> None:
    done = runtime("claude_code", "", ("--gate", _gate(tmp_path, "gate.json", "block", stop=True)))
    assert _body(done).get("decision") == "block" and "hookSpecificOutput" not in _body(done), done.stdout

"""A Stop whose payload cannot be read refuses in the vendor's Stop grammar, and the refusals are bounded.

Plugin Stop hooks share the pre-tool `gate.json`, so they say `--stop`; an unreadable payload cannot
name a session, so a per-repo ledger counts the refusals: `REENTRY_CAP`, then a loud warning and a held
gate-log record, never a silent allow.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from bundle_fixtures import ALL_ROOTS, bundle, hook_commands, make_members, project, write
from conftest import run_hook_command

from chock.gate import runtime_bundle
from chock.gate.stop_reentry import REENTRY_CAP
from chock.gate.unreadable_stop import UNREADABLE_STOP_LEDGER, UNREADABLE_STOP_WINDOW_SECONDS
from chock.guardrails.plugin import PROTECT_ID
from chock.plugin.bundle_build import CLIENTS, merged_files
from chock.plugin.gate_package import gate_reach

LEDGER = Path(".chock", "state", UNREADABLE_STOP_LEDGER)
GATE_LOG = Path(".chock", "log", "gate-events.jsonl")


def _body(proc: object) -> dict:
    try:
        body = json.loads(proc.stdout or "null")
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _top_block(proc: object) -> bool:
    body = _body(proc)
    return proc.returncode == 0 and body.get("decision") == "block" and "hookSpecificOutput" not in body


#: Each vendor's own Stop refusal, as its client reads it; a pre-tool deny does not end a Stop.
STOP_REFUSALS = {
    "claude": _top_block,
    "codex": _top_block,
    "devin": _top_block,
    "copilot": lambda p: p.returncode == 0 and (_body(p).get("hookSpecificOutput") or {}).get("decision") == "block",
    "cursor": lambda p: p.returncode == 2,
}


def _stop_command(package: Path) -> str:
    (command,) = [
        c
        for c in hook_commands(json.loads(next(package.rglob("hooks.json")).read_text("utf-8")))
        if " --stop" in c and PROTECT_ID not in c
    ]
    return command


def _run(command: str, repo: Path, payload: str, package: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ALL_ROOTS}
    env.update(dict.fromkeys(ALL_ROOTS, package.as_posix()))
    return run_hook_command(command, repo, payload, env=env)


def _clean_stop(client: str, repo: Path) -> str:
    raw = runtime_bundle._wire_raw(CLIENTS[client].agent, "stop")
    return json.dumps({**raw, "cwd": str(repo), "session_id": "s", "conversation_id": "c", "generation_id": "g"})


#: Every client's package as it ships: one member alone, and the merged bundle.
SHAPES = [(name, merged) for merged in (False, True) for name in sorted(CLIENTS)]


@pytest.fixture(params=SHAPES, ids=[f"{n}-{'bundle' if m else 'single'}" for n, m in SHAPES])
def installed(request, tmp_path: Path) -> tuple[str, Path, Path, str]:
    """A client's gate package with its Stop command, in a clean git project."""
    client, merged = request.param
    members = make_members(tmp_path / "m")
    if merged:
        files = merged_files(client, bundle(members), members, tmp_path)
    else:
        files = CLIENTS[client].files(members[0].policy_dir, members[0].manifest, tmp_path)
    package = write(tmp_path / "pkg", files)
    return client, package, project(tmp_path), _stop_command(package)


def test_an_unreadable_stop_is_refused_in_the_vendors_stop_grammar(
    installed,
) -> None:
    client, package, repo, command = installed
    done = _run(command, repo, "not json", package)
    assert STOP_REFUSALS[client](done), (client, done.returncode, done.stdout)
    assert "could not read" in done.stderr, (client, done.stderr)


def test_a_readable_clean_stop_is_still_allowed(
    installed,
) -> None:
    client, package, repo, command = installed
    done = _run(command, repo, _clean_stop(client, repo), package)
    assert not STOP_REFUSALS[client](done) and done.returncode == 0, (client, done.stdout, done.stderr)
    assert "block" not in done.stdout, (client, done.stdout)
    assert not (repo / LEDGER).exists(), "a readable stop never touches the unreadable-stop ledger"


def test_the_cap_ends_refusing_with_a_warning_and_a_held_record(
    installed,
) -> None:
    client, package, repo, command = installed
    for turn in range(REENTRY_CAP):
        done = _run(command, repo, "", package)
        assert STOP_REFUSALS[client](done), (client, turn, done.stdout)
    assert "next one ends the turn unchecked" in done.stdout + done.stderr, (client, done.stderr)
    after = _run(command, repo, "", package)
    assert after.returncode == 0 and not STOP_REFUSALS[client](after), (client, after.stdout)
    assert "could not read, so none of them was judged" in after.stderr, (client, after.stderr)
    records = [json.loads(x) for x in (repo / GATE_LOG).read_text("utf-8").splitlines()]
    held = [r for r in records if r.get("would_block")]
    assert [r["reentry"] for r in held] == [REENTRY_CAP + 1] and held[0]["verdict"] == "warn", (client, records)


def test_a_refusal_ages_out_of_the_window(installed) -> None:
    client, package, repo, command = installed
    for _ in range(REENTRY_CAP):
        _run(command, repo, "x", package)
    ledger = repo / LEDGER
    old = [json.loads(x) for x in ledger.read_text("utf-8").splitlines()]
    for record in old:
        record["at"] -= UNREADABLE_STOP_WINDOW_SECONDS + 1
    ledger.write_text("".join(json.dumps(r) + "\n" for r in old), encoding="utf-8")
    assert STOP_REFUSALS[client](_run(command, repo, "x", package)), "stale refusals do not count"


def test_a_damaged_ledger_never_lets_a_stop_through(installed) -> None:
    client, package, repo, command = installed
    ledger = repo / LEDGER
    ledger.parent.mkdir(parents=True)
    ledger.write_text('not json\n{"phase": "unreadable-stop", "verdict": "block"}\n[1]\n', encoding="utf-8")
    assert STOP_REFUSALS[client](_run(command, repo, "x", package)), "records that do not parse count as none"


def test_a_ledger_that_cannot_be_written_keeps_refusing(installed) -> None:
    client, package, repo, command = installed
    (repo / ".chock").mkdir()
    (repo / ".chock" / "state").write_text("a file where the directory belongs", encoding="utf-8")
    for _ in range(REENTRY_CAP + 2):
        assert STOP_REFUSALS[client](_run(command, repo, "x", package)), "nothing to count: only a refusal is safe"


def test_an_unreadable_pre_tool_call_is_never_capped(installed) -> None:
    client, package, repo, _ = installed
    hooks = hook_commands(json.loads(next(package.rglob("hooks.json")).read_text("utf-8")))
    pre = [c for c in hooks if " --stop" not in c]
    assert pre or gate_reach(CLIENTS[client].agent)[0] is None, "only a stop-only client lacks a pre-tool hook"
    for command in pre:
        for _ in range(REENTRY_CAP + 2):
            done = _run(command, repo, "x", package)
            assert "could not read" in done.stderr and "none of them was judged" not in done.stderr, (
                client,
                done.stderr,
            )
    assert not (repo / LEDGER).exists()


# --- the repo runtime `chock sync` writes: the stop gate's own folder names the event ----------


def _stop_gate(tmp_path: Path) -> str:
    path = tmp_path / "stop" / "gate.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"kind": "script", "on": ["tool_call"], "action": "block", "params": {}}), "utf-8")
    return str(path)


def test_the_repo_wiring_is_bounded_the_same_way(tmp_path: Path) -> None:
    runtime = tmp_path / "claude_code.py"
    runtime.write_text(runtime_bundle.render("claude_code"), encoding="utf-8")
    argv = [sys.executable, str(runtime), "--gate", _stop_gate(tmp_path)]
    runs = [
        subprocess.run(argv, cwd=tmp_path, input="", capture_output=True, text=True) for _ in range(REENTRY_CAP + 1)
    ]
    assert all(_top_block(done) for done in runs[:REENTRY_CAP]), [d.stdout for d in runs]
    last = runs[-1]
    assert last.returncode == 0 and "decision" not in _body(last) and "none of them was judged" in last.stdout
    assert "none of them was judged" in last.stderr

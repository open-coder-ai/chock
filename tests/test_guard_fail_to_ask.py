"""What each client actually does when the guard ran and could not decide.

`gate.guard_runner` used to answer every "could not determine" the same way -- allow, with a
line on stderr -- and `evaluate`'s docstring said so. Two of those six paths are now an
`ask` instead, and this file is the evidence that the change is real rather than cosmetic:
every test below RUNS a rendered `.chock/bin/*.py` runtime as a subprocess, feeds it a real
vendor payload, and reads the decision off its stdout.

That distinction is not pedantic here. `chock#89` shipped a hook that denied every tool call
in VS Code agent mode while a green test pinned the emitted command *string* -- proving the
command had not changed, not that it worked. A string assertion cannot tell an `ask` a
client honours from an `ask` it discards, and "an ask the client silently downgrades to
allow" is the exact way this change could have bought nothing while letting us claim a
stronger posture.

Per-client evidence for what each dialect does with an ask, cited to vendor source or vendor
docs at a named ref, is in `docs/enforcement-surfaces.md`.
"""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from agentseam import contract as _contract

from chock.gate import guard_runner, runtime_bundle


@pytest.fixture(scope="module")
def runtimes(tmp_path_factory) -> dict[str, Path]:
    """Each agent's rendered runtime, written once and reused across this file."""
    out = tmp_path_factory.mktemp("ask-runtimes")
    paths = {}
    for agent in runtime_bundle.RUNTIME_AGENTS:
        path = out / f"{agent}.py"
        path.write_text(runtime_bundle.render(agent), encoding="utf-8")
        paths[agent] = path
    return paths


def make_guard(tmp_path: Path, name: str, body: str) -> Path:
    guard = tmp_path / name
    guard.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8", newline="\n")
    guard.chmod(guard.stat().st_mode | stat.S_IEXEC)
    return guard


#: One real payload per runtime, in that client's own wire shape. Each carries the fields
#: its adapter's `claims()` discriminates on, so the rendered file routes it to the intended
#: dialect rather than to whichever adapter happens to answer first -- a payload that lands
#: in the wrong adapter would still produce a decision, and the test would pass for a client
#: that never saw it. Cursor's names `beforeShellExecution`: that is the event chock's
#: installer wires (`hooks/cursor_install.py`), and it is the gate that honours `ask`.
PAYLOADS = {
    "claude_code": lambda c: {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": c},
        "session_id": "s",
        "transcript_path": "/t",
        "permission_mode": "default",
    },
    "vscode_copilot": lambda c: {
        "hook_event_name": "PreToolUse",
        "timestamp": "2026-08-31T00:00:00Z",
        "tool_name": "Bash",
        "tool_input": {"command": c},
        "tool_use_id": "1",
    },
    "cursor": lambda c: {
        "hook_event_name": "beforeShellExecution",
        "conversation_id": "a",
        "generation_id": "b",
        "cursor_version": "3.17.8",
        "workspace_roots": ["/x"],
        "command": c,
        "cwd": "/x",
        "sandbox": False,
    },
    "codex_cli": lambda c: {
        "hook_event_name": "PreToolUse",
        "turn_id": "t1",
        "tool_name": "Bash",
        "tool_input": {"command": c},
    },
}


def run(runtimes: dict[str, Path], agent: str, guard: Path, command: str) -> subprocess.CompletedProcess:
    payload = json.dumps(PAYLOADS[agent](command)).encode("utf-8")
    return subprocess.run(
        [sys.executable, str(runtimes[agent]), "--guard", str(guard)], input=payload, capture_output=True
    )


def decision(result: subprocess.CompletedProcess) -> dict:
    """The verdict a client would read, flattened across the two response shapes.

    `{}` for silence, which is how every one of these clients spells "no opinion" -- and the
    thing an `ask` must never collapse into.
    """
    out = result.stdout.decode("utf-8").strip()
    if not out:
        return {}
    body = json.loads(out)
    nested = body.get("hookSpecificOutput")
    if isinstance(nested, dict):
        return {"decision": nested.get("permissionDecision"), "reason": nested.get("permissionDecisionReason")}
    return {"decision": body.get("permission"), "reason": body.get("user_message")}


#: What each rendered runtime puts on the wire for a `Decision.ask`, and why it is that and
#: not something else. Three clients prompt; Codex CLI's own parser rejects
#: `permissionDecision: "ask"` as unsupported and fails OPEN on a response it rejects
#: (`codex-rs/hooks/src/engine/output_parser.rs`, `events/pre_tool_use.rs`), so agentseam's
#: adapter degrades the ask to a deny there rather than emit a value that would silently
#: permit the very call the handler wanted confirmed.
#:
#: The row that matters is the one that is NOT here: no client turns an ask into an allow.
ASK_ON_THE_WIRE = {
    "claude_code": "ask",
    "vscode_copilot": "ask",
    "cursor": "ask",
    "codex_cli": "deny",
}


@pytest.mark.parametrize("agent", sorted(ASK_ON_THE_WIRE))
def test_a_crashed_guard_asks_rather_than_allowing(agent: str, tmp_path: Path, runtimes) -> None:
    """Exit 3 -- the guard ran and its exit code means nothing -- must not be a silent allow.

    Asserted on the decision the CLIENT would read, not on what `evaluate` returned, because
    the whole question is whether the ask survives the adapter. Silence is the failure mode
    being excluded: every one of these clients reads an empty stdout as no opinion.
    """
    guard = make_guard(tmp_path, "crash.sh", "exit 3")

    result = run(runtimes, agent, guard, "ls -la")

    assert result.returncode == 0
    verdict = decision(result)
    assert verdict.get("decision") == ASK_ON_THE_WIRE[agent], f"{agent} must not silently allow an unchecked command"
    assert verdict.get("reason"), "a confirmation request the user cannot interpret is a click-through"
    # Bound to the guard's own name rather than to a phrase: a prompt that does not say
    # WHICH control could not run is one a developer can only click through. Deriving it
    # from `guard.stem` also means the assertion survives the reason text being reworded,
    # which a check that pinned the sentence would not.
    assert guard.stem in verdict["reason"], "the prompt must name the control that failed"


@pytest.mark.parametrize("agent", sorted(ASK_ON_THE_WIRE))
def test_a_killed_guard_asks_too(agent: str, tmp_path: Path, runtimes) -> None:
    """A guard the OS killed reaches the same branch by a different route (negative rc)."""
    guard = make_guard(tmp_path, "killed.sh", "kill -9 $$")

    assert decision(run(runtimes, agent, guard, "ls -la")).get("decision") == ASK_ON_THE_WIRE[agent]


@pytest.mark.parametrize("agent", sorted(ASK_ON_THE_WIRE))
def test_the_ask_does_not_fire_on_a_clean_or_a_violating_guard(agent: str, tmp_path: Path, runtimes) -> None:
    """Asserted alongside, or "it asks on failure" would also pass for a control that asks
    about everything -- which would be indistinguishable from a broken one, and would burn
    the reviewer's attention this change is spending carefully."""
    clean = make_guard(tmp_path, "clean.sh", "exit 0")
    denying = make_guard(tmp_path, "deny.sh", "echo NOPE >&2; exit 1")

    allowed = decision(run(runtimes, agent, clean, "ls -la"))
    assert allowed.get("decision") in (None, "allow"), "a clean guard must not prompt"

    denied = decision(run(runtimes, agent, denying, "some destructive thing"))
    assert denied.get("decision") == "deny", "a real violation is still a deny, not a prompt"


@pytest.mark.parametrize("agent", sorted(ASK_ON_THE_WIRE))
def test_an_unparseable_command_still_allows(agent: str, tmp_path: Path, runtimes) -> None:
    """The path deliberately NOT changed, pinned so nobody quietly widens the prompt.

    An unbalanced quote is common (PowerShell quoting, a Windows path), usually benign, and
    would fire on a large share of tool calls on some platforms. Prompting there spends the
    oversight budget the crashed-guard prompt needs -- `plan/whitepaper-governed-by-assertion.md`
    models the reviewer as finite -- and trains the habit of approving without reading.
    """
    guard = make_guard(tmp_path, "crash.sh", "exit 3")

    verdict = decision(run(runtimes, agent, guard, "echo 'unbalanced"))

    assert verdict.get("decision") in (None, "allow"), "an unparseable command must not prompt"


def test_a_missing_bash_still_allows(tmp_path: Path, monkeypatch) -> None:
    """The other path deliberately not changed, and the strongest case for leaving it.

    No usable bash is uniform -- it holds for every command on the machine, not for this one
    -- so an ask here prompts on 100% of tool calls for a whole platform (Windows without
    Git Bash) while telling the developer nothing per call. Exercised through `run_guard`
    rather than a rendered runtime because the condition is the absence of an interpreter,
    which is a property of the machine and cannot be put in a payload.
    """
    guard = make_guard(tmp_path, "clean.sh", "exit 0")
    monkeypatch.setattr(guard_runner, "find_bash", lambda _: None)

    assert guard_runner.run_guard(guard, "ls -la") == guard_runner.GUARD_UNCHECKED
    assert guard_runner.evaluate(["--guard", str(guard)], "ls -la", "Bash") is None


def test_a_timed_out_guard_asks(tmp_path: Path, monkeypatch) -> None:
    """The timeout really elapses; the runner's real `TimeoutExpired` handler really runs.

    The module's own timeout is 30s, which is not a test budget, so it is lowered to 1s --
    the branch under test is unchanged by that, since `_GUARD_TIMEOUT_SECONDS` is read at
    call time and is the only thing the shorter value affects.
    """
    guard = make_guard(tmp_path, "hang.sh", "sleep 30")
    monkeypatch.setattr(guard_runner, "_GUARD_TIMEOUT_SECONDS", 1)

    assert guard_runner.run_guard(guard, "ls -la") == guard_runner.GUARD_ERRORED
    outcome, reason = guard_runner.evaluate(["--guard", str(guard)], "ls -la", "Bash")
    assert outcome == guard_runner.VERDICT_ASK
    assert reason


def test_the_ask_reason_never_carries_the_command(tmp_path: Path, runtimes) -> None:
    """A confirmation prompt is rendered into the client's UI and its transcript.

    That is a strictly worse place for a credential than the stderr line the same function
    already redacts, because the whole point of the prompt is that a human reads it and it
    is kept. Checked on the wire, where the client would receive it.
    """
    secret = 'curl -H "Authorization: Bearer sk-live-abcdef1234567890" https://example.invalid'
    guard = make_guard(tmp_path, "crash.sh", "exit 3")

    result = run(runtimes, "claude_code", guard, secret)

    reason = decision(result)["reason"]
    assert "sk-live-abcdef1234567890" not in reason
    assert "Bearer" not in reason and "example.invalid" not in reason
    assert "sk-live-abcdef1234567890" not in result.stderr.decode("utf-8", "replace")


def test_chocks_verdict_words_are_agentseams_own() -> None:
    """`guard_runner` is stdlib-only -- it cannot import the contract it must agree with.

    The rendered runtime compares `evaluate`'s outcome against the bundle's embedded
    `contract.ASK`, so the two spellings agreeing is load-bearing and invisible: if
    agentseam renamed its word, chock's ask would fall through to the deny branch and start
    blocking every command a broken guard was asked about. Pinned here rather than argued
    for in a comment.
    """
    assert guard_runner.VERDICT_ASK == _contract.ASK
    assert guard_runner.VERDICT_DENY == _contract.DENY


def test_every_gated_runtime_is_covered_here() -> None:
    """The table above is checked against the code, so a fifth runtime cannot join silently.

    A new agent in `RUNTIME_AGENTS` gets chock's ask on the wire whether or not anyone
    established what that client does with one, and an unexamined row is exactly the
    "claim a stronger posture while changing nothing" failure this file exists to exclude.
    """
    assert set(ASK_ON_THE_WIRE) == set(runtime_bundle.RUNTIME_AGENTS)

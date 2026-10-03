"""Judge a tool call by its name: the `tool_call` event, plus the session log's writers. Stdlib only.

A policy gate declaring `"on": ["tool_call"]` names tool globs in `params.tools`; a hook fires for
that call and this module asks the gate's own check. `content_regex` reads the tool input as JSON
text, `script` gets `{"event": "tool_call", "repo_root", "tool", "input", "session"}` on stdin and
answers by exit code, as it does at every other event. It is a sibling of `write_gate`, and like
it never imports chock: the vendored runtime carries it.
"""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

from .budget import allowed_seconds, engine_deadline, time_left
from .session_log import (
    session_for,
    session_outcome,
    session_record,
    tool_call_input,
)
from .write_gate import repo_root_for

TOOL_CALL_FLAG = "--tool-call"
RECORD_FLAG = "--record"
TOOL_CALL_EVENT = "tool_call"
_TOOL_CALL_PRE = "pre_tool"
_TOOL_CALL_POST = ("post_tool", "tool_failure")
_TOOL_CALL_SCRIPT_KIND = "script"
_TOOL_CALL_REGEX_KIND = "content_regex"
_TOOL_CALL_BLOCKED = "blocked"
_TOOL_CALL_NEEDS_SESSION = frozenset({_TOOL_CALL_SCRIPT_KIND})
#: A script's exit code -> the verdict it speaks, the same codes a script speaks at every event.
_TOOL_CALL_EXIT_VERDICTS = {0: None, 1: "deny", 3: "escalate", 4: "warn"}
#: The gate's declared `action` is a ceiling: a verdict (or a refusal it could not decide) never
#: goes past it, so a warn gate never blocks and an ask gate never denies outright.
_TOOL_CALL_CEILING = {"block": "deny", "ask": "escalate", "warn": "warn"}
_TOOL_CALL_RANK = {"warn": 0, "escalate": 1, "deny": 2}
_TOOL_CALL_UNDECIDED = " -- refusing rather than allowing what it never judged"


def _flag_path(argv, flag):
    if flag in argv:
        index = argv.index(flag)
        if index + 1 < len(argv):
            return Path(argv[index + 1])
    return None


def tool_call_matches(globs, tool):
    """Whether `tool` (a tool name, exact case) matches any glob; no globs match nothing."""
    return any(fnmatch.fnmatchcase(tool, str(glob)) for glob in globs)


def _tool_call_refusal(spec, spoken):
    return spoken or str(spec.get("message") or "").strip() or "blocked by a chock tool_call gate"


def _tool_call_regex(spec, tool_input):
    """`deny` verdict when the input, as JSON text, matches the gate's `content_pattern`."""
    text = json.dumps(tool_input, sort_keys=True, ensure_ascii=False)
    if re.search(str((spec.get("params") or {}).get("content_pattern", "")), text):
        return ("deny", _tool_call_refusal(spec, ""))
    return None


def _tool_call_script(spec, root, payload, deadline=None):
    """Run the policy's script on `payload`; a missing script, crash or timeout refuses."""
    named = str((spec.get("params") or {}).get("script", ""))
    script = Path(root) / named
    if not script.is_file():
        return ("deny", f"script gate: {named!r} is not installed{_TOOL_CALL_UNDECIDED}")
    deadline = engine_deadline() if deadline is None else deadline
    argv = [sys.executable, str(script)]
    try:
        proc = subprocess.run(  # noqa: S603 -- the script is the policy's own, named in its manifest
            argv,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(root),
            timeout=time_left(deadline, argv),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        budget = f"gave no verdict within {allowed_seconds(exc)}"
        return ("deny", f"script gate: {script.name} {budget}{_TOOL_CALL_UNDECIDED}")
    except OSError as exc:
        return ("deny", f"script gate: {script.name} could not run ({exc}){_TOOL_CALL_UNDECIDED}")
    spoken = ((proc.stderr or "") + (proc.stdout or "")).strip()
    if proc.returncode in _TOOL_CALL_EXIT_VERDICTS:
        verdict = _TOOL_CALL_EXIT_VERDICTS[proc.returncode]
        return None if verdict is None else (verdict, spoken or f"blocked by {script.name}")
    first = spoken.splitlines()[0] if spoken else ""
    detail = f": {first}" if first else ""
    return ("deny", f"script gate: {script.name} exited {proc.returncode}{detail}{_TOOL_CALL_UNDECIDED}")


def _tool_call_verdict(spec, root, event, deadline):
    """None to allow, else (verdict, message) for this call; a kind a tool call cannot answer refuses."""
    tool, tool_input = str(event.tool or ""), tool_call_input(event)
    kind = spec.get("kind")
    if kind == _TOOL_CALL_REGEX_KIND:
        return _tool_call_regex(spec, tool_input)
    if kind == _TOOL_CALL_SCRIPT_KIND:
        payload = {
            "event": TOOL_CALL_EVENT,
            "repo_root": str(root),
            "tool": tool,
            "input": tool_input,
            "session": session_for(event, root),
        }
        return _tool_call_script(spec, root, payload, deadline)
    return ("deny", f"chock tool_call gate: kind {kind!r} cannot judge a tool call{_TOOL_CALL_UNDECIDED}")


def _tool_call_capped(spec, verdict):
    """`verdict` held to the gate's declared action; an unknown action keeps the verdict as spoken."""
    ceiling = _TOOL_CALL_CEILING.get(spec.get("action", "block"))
    if verdict is None or ceiling is None:
        return verdict
    return (min(verdict[0], ceiling, key=_TOOL_CALL_RANK.__getitem__), verdict[1])


def _tool_call_spec(gate):
    """The compiled gate as a dict, or (None, refusal) when the install is broken."""
    if not gate.exists():
        return None, (
            f"chock gate {gate} is missing, so this tool call cannot be checked. "
            "Run `chock sync --repo .` to rebuild the compiled gates."
        )
    try:
        return json.loads(gate.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return (
            None,
            f"chock could not read {gate}: {exc}. Refusing rather than reporting an allow it never established.",
        )


def evaluate_tool_call(argv, event):
    """The decision a tool_call gate earns this call, or None; also logs the call for the session.

    `--tool-call <gate>` judges a PreToolUse call and, for a gate whose check reads the session,
    logs it after the verdict, so the script reads prior calls only. `--record <gate>` logs what
    a call came to, after it ran (a vendor's PostToolUse and failure events).
    """
    recording = _flag_path(argv, RECORD_FLAG)
    if recording is not None:
        if event.event in _TOOL_CALL_POST:
            session_record(repo_root_for(event, recording), event, "post", session_outcome(event))
        return None
    gate = _flag_path(argv, TOOL_CALL_FLAG)
    if gate is None or event.event != _TOOL_CALL_PRE:
        return None
    spec, broken = _tool_call_spec(gate)
    if spec is None:
        return ("deny", broken)
    root = repo_root_for(event, gate)
    verdict = None
    if TOOL_CALL_EVENT in spec.get("on", []) and tool_call_matches(
        (spec.get("params") or {}).get("tools", []), str(event.tool or "")
    ):
        verdict = _tool_call_capped(spec, _tool_call_verdict(spec, root, event, engine_deadline()))
    if spec.get("kind") in _TOOL_CALL_NEEDS_SESSION:
        session_record(root, event, "pre", _TOOL_CALL_BLOCKED if verdict and verdict[0] == "deny" else None)
    return verdict

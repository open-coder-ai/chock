"""Judge a submitted prompt: the `prompt_submit` event. Stdlib only; like `tool_call_gate`, never imports chock.

A policy gate declaring `"on": ["prompt_submit"]` runs when the person submits a prompt, before the model
reads it. `content_regex` reads the prompt text; `script` gets `{"event": "prompt_submit", "repo_root",
"prompt", "session"}` on stdin and answers by exit code. A refusal is the gate's own message, or a fixed
engine message naming the policy and the cause: a script's own words are never shown at this event, so
nothing from the prompt can reach the refusal or the log.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .budget import (
    PATTERN_SECONDS,
    allowed_seconds,
    close_judge,
    engine_deadline,
    engine_remaining,
    isolated_child,
    judge_patterns,
    pattern_judge,
    run_tree,
    time_left,
)
from .session_log import session_for
from .tool_call_gate import (
    _TOOL_CALL_UNDECIDED,
    _flag_path,
    _tool_call_capped,
    asked_as_policy,
)
from .write_gate import repo_root_for

PROMPT_SUBMIT_FLAG = "--prompt-submit"
PROMPT_SUBMIT_EVENT = "prompt_submit"
_PROMPT_REGEX_KIND = "content_regex"
_PROMPT_SCRIPT_KIND = "script"
_PROMPT_DEFAULT_MESSAGE = "blocked by a chock prompt_submit gate"
#: A script's exit code -> the verdict it speaks; its output is never read into the refusal.
_PROMPT_EXIT_VERDICTS = {0: None, 1: "deny", 3: "escalate", 4: "warn"}


def _prompt_message(spec):
    return str(spec.get("message") or "").strip() or _PROMPT_DEFAULT_MESSAGE


def _prompt_spec(gate):
    """The compiled gate as a dict, or (None, refusal) when the install is broken."""
    if not gate.exists():
        return None, (
            f"chock gate {gate} is missing, so this prompt cannot be checked. "
            "Run `chock sync --repo .` to rebuild the compiled gates."
        )
    try:
        return json.loads(gate.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return (
            None,
            f"chock could not read {gate}: {type(exc).__name__}{_TOOL_CALL_UNDECIDED}",
        )


def _prompt_regex(spec, prompt, deadline, policy):
    """`deny` verdict when the prompt matches the gate's `content_pattern`, under the engine's pattern deadline."""
    pattern = str((spec.get("params") or {}).get("content_pattern", ""))
    judge = pattern_judge()
    try:
        hits, why = judge_patterns(judge, [(pattern, [prompt])], min(PATTERN_SECONDS, engine_remaining(deadline)))
    finally:
        close_judge(judge)
    if why:
        return ("deny", f"content_regex gate {policy}: {why}{_TOOL_CALL_UNDECIDED}")
    return ("deny", _prompt_message(spec)) if hits[0] else None


def _prompt_script(spec, root, payload, deadline, policy):
    """Run the policy's script on `payload`; only its exit code is used, never its output."""
    named = str((spec.get("params") or {}).get("script", ""))
    script = Path(root) / named
    refusing = f"chock prompt_submit gate {policy}: script"
    if not script.is_file():
        return ("deny", f"{refusing} not installed{_TOOL_CALL_UNDECIDED}")
    argv, env = isolated_child([sys.executable, str(script)])
    try:
        proc = run_tree(
            argv,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(root),
            env=env,
            timeout=time_left(deadline, argv),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return ("deny", f"{refusing} gave no verdict within {allowed_seconds(exc)}{_TOOL_CALL_UNDECIDED}")
    except OSError as exc:
        return ("deny", f"{refusing} could not run ({type(exc).__name__}){_TOOL_CALL_UNDECIDED}")
    if proc.returncode in _PROMPT_EXIT_VERDICTS:
        verdict = _PROMPT_EXIT_VERDICTS[proc.returncode]
        return None if verdict is None else (verdict, _prompt_message(spec))
    return ("deny", f"{refusing} exited {proc.returncode}{_TOOL_CALL_UNDECIDED}")


def _prompt_verdict(spec, root, event, deadline, policy):
    """None to allow, else (verdict, message) for this prompt; a prompt it cannot read refuses."""
    prompt = getattr(event, "prompt", None)
    if not isinstance(prompt, str):
        return ("deny", f"chock prompt_submit gate {policy}: the client sent no prompt text{_TOOL_CALL_UNDECIDED}")
    kind = spec.get("kind")
    if kind == _PROMPT_REGEX_KIND:
        return _prompt_regex(spec, prompt, deadline, policy)
    if kind == _PROMPT_SCRIPT_KIND:
        payload = {
            "event": PROMPT_SUBMIT_EVENT,
            "repo_root": str(root),
            "prompt": prompt,
            "session": session_for(event, root),
        }
        return _prompt_script(spec, root, payload, deadline, policy)
    return ("deny", f"chock prompt_submit gate: kind {kind!r} cannot judge a prompt{_TOOL_CALL_UNDECIDED}")


def evaluate_prompt_submit(argv, event):
    """The decision a prompt_submit gate earns this prompt, or None: `--prompt-submit <gate>` names the gate."""
    gate = _flag_path(argv, PROMPT_SUBMIT_FLAG)
    if gate is None or event.event != PROMPT_SUBMIT_EVENT:
        return None
    spec, broken = _prompt_spec(gate)
    if spec is None:
        return ("deny", broken)
    if PROMPT_SUBMIT_EVENT not in spec.get("on", []):
        return None
    policy = gate.parent.parent.name
    verdict = _prompt_verdict(spec, repo_root_for(event, gate), event, engine_deadline(), policy)
    return asked_as_policy(_tool_call_capped(spec, verdict), policy, "prompt", _PROMPT_DEFAULT_MESSAGE)

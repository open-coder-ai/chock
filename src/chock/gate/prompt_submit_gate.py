"""Judge a submitted prompt: the `prompt_submit` event. Stdlib only; like `tool_call_gate`, never imports chock.

A policy gate declaring `"on": ["prompt_submit"]` runs when the person submits a prompt, before the model
reads it. `content_regex` reads the prompt text; `script` gets `{"event": "prompt_submit", "repo_root",
"prompt", "session"}` on stdin and answers by exit code. The refusal is the gate's own message: the
prompt, and the text that matched, are never echoed back or logged.
"""

from __future__ import annotations

import json

from .budget import PATTERN_SECONDS, close_judge, engine_deadline, engine_remaining, judge_patterns, pattern_judge
from .session_log import session_for
from .tool_call_gate import (
    _TOOL_CALL_UNDECIDED,
    _flag_path,
    _tool_call_capped,
    _tool_call_script,
)
from .write_gate import repo_root_for

PROMPT_SUBMIT_FLAG = "--prompt-submit"
PROMPT_SUBMIT_EVENT = "prompt_submit"
_PROMPT_REGEX_KIND = "content_regex"
_PROMPT_SCRIPT_KIND = "script"
_PROMPT_DEFAULT_MESSAGE = "blocked by a chock prompt_submit gate"


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
        return _tool_call_script(spec, root, payload, deadline)
    return ("deny", f"chock prompt_submit gate: kind {kind!r} cannot judge a prompt{_TOOL_CALL_UNDECIDED}")


def _prompt_free(verdict, spec, prompt):
    """`verdict` with its message swapped for the gate's own when it carries the prompt text."""
    if verdict is None or not isinstance(prompt, str) or not prompt.strip():
        return verdict
    return verdict if prompt.strip() not in verdict[1] else (verdict[0], _prompt_message(spec))


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
    return _prompt_free(_tool_call_capped(spec, verdict), spec, event.prompt)

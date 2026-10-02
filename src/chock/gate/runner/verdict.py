"""Gate runner: evaluate a compiled gate, cap its verdict, and conclude with an exit code."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .actor import _ask_answered, _ask_refusal, _judged_event, agent_signal, rollout
from .constants import (
    _ACTION_RANK,
    _EVENT_NAME,
    _GIT_EVENTS,
    _MIN_COMPILED_PATH_DEPTH,
    _OBSERVE_NOTE,
    _ROLLOUT_CEILING,
    ACTION_ASK,
    ACTION_BLOCK,
    ACTION_WARN,
    AGENT_EVENTS,
    ALLOW_ENV,
    EXIT_ASK,
    EXIT_WARN,
    ROLLOUT_ENFORCE,
    ROLLOUT_OBSERVE,
    STOP_EVENT,
    TOOL_USE_EVENT,
    VERDICT_ERROR,
)
from .context import GateResult
from .kinds import KINDS
from .log import _actor, _held_record, _log_outcome, _log_script_hook
from .material import _context, _params, own_paths
from .report import _annotate_safely, _annotation, _encodable, _github_actions, _reason, _report_refusal, ci_inert


# >>> gate.py 14
def _policy_id(gate_path: Path) -> str | None:
    """The policy a compiled gate belongs to, from `.chock/compiled/<id>/<surface>/`, else None."""
    parents = gate_path.resolve().parents
    if len(parents) < _MIN_COMPILED_PATH_DEPTH or parents[2].name != "compiled":
        return None
    return parents[1].name


def _verdict(result: GateResult, declared: str, level: str = ROLLOUT_ENFORCE) -> str:
    """`allow`, or the action this violation takes: what the kind chose, capped by the declared action and the rollout."""
    if result.allowed:
        return "allow"
    chosen = result.verdict or declared
    return min(chosen, declared, _ROLLOUT_CEILING[level], key=_ACTION_RANK.__getitem__)


# >>> gate.py 17
def _deliver(verdict: str, result: GateResult, spec: dict, event: str, policy_id: str | None) -> int:
    """Report a `warn` or `ask` in this event's own channel and return its exit code."""
    reason = _reason(result, spec, TOOL_USE_EVENT if event in AGENT_EVENTS else event, policy_id)
    if event in AGENT_EVENTS:
        print(reason, file=sys.stderr)
        # The turn's end has nobody to ask and nothing to withhold: a Stop ask is a warning.
        return EXIT_ASK if verdict == ACTION_ASK and event != STOP_EVENT else EXIT_WARN
    if event == "ci":
        if _github_actions() and result.findings:
            print(_encodable(ci_inert(f"gate: warning: {reason}"), sys.stderr), file=sys.stderr)
        else:
            print(_encodable(_annotation(policy_id, reason), sys.stdout))
        return 0
    print(f"gate: warning: {reason}", file=sys.stderr)
    return 0


# >>> gate.py 19
def script_verdict(policy_id: str, event: str, code: int, repo_root: Path) -> int:
    """The exit a script-backed git hook takes for its script's exit `code` (3 asks, 4 warns).

    The script already printed its own words. A warn is allowed; an ask is refused unless a person
    named the policy in `CHOCK_ALLOW` and no agent marker is on the command.
    """
    signal = agent_signal(repo_root)
    level = rollout(repo_root, event, signal)
    if code == EXIT_WARN:
        _log_script_hook(policy_id, event, ACTION_WARN, repo_root, _actor(signal))
        return 0
    if level == ROLLOUT_OBSERVE:
        print(_OBSERVE_NOTE.format(policy=policy_id, held=ACTION_ASK), file=sys.stderr)
        _log_script_hook(
            policy_id, event, ACTION_WARN, repo_root, {**_held_record(ACTION_ASK, level), **_actor(signal)}
        )
        return 0
    if _ask_answered(policy_id, signal):
        print(f"gate: {policy_id} asked; allowed by {ALLOW_ENV}.", file=sys.stderr)
        _log_script_hook(policy_id, event, "allow", repo_root, {"override": ALLOW_ENV, **_actor(signal)})
        return 0
    print(_ask_refusal(policy_id, signal), file=sys.stderr)
    _log_script_hook(policy_id, event, ACTION_ASK, repo_root, _actor(signal))
    return 1


@dataclass(frozen=True)
class Evaluation:
    """A gate run up to its verdict: what the kind found, and the actor and rollout level it was judged under."""

    spec: dict
    result: GateResult
    level: str
    signal: str | None
    judged: str


def evaluate(
    gate_path: Path,
    event: str,
    push_stdin: str | None,
    repo_root: Path,
    base: str | None = None,
    head_ref: str | None = None,
    writes: Mapping[str, str] | None = None,
    added: Mapping[str, str] | None = None,
    session: Mapping[str, object] | None = None,
) -> Evaluation | tuple[int, str]:
    """Run a compiled gate's kind without reporting or logging: an Evaluation, or (exit code, verdict) when it ends early."""
    gate_path = Path(gate_path)
    if not gate_path.exists():
        print(
            "gate: the compiled gate this hook names is missing, so the install is incomplete. "
            "Run `chock sync --repo .` to rebuild the compiled gates.",
            file=sys.stderr,
        )
        return 2, VERDICT_ERROR
    try:
        spec = json.loads(gate_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"gate: cannot read the compiled gate this hook names: {type(exc).__name__}", file=sys.stderr)
        return 2, VERDICT_ERROR
    if event == "ci":
        name, covered = "ci", "commit" in spec.get("on", [])
    else:
        name = _EVENT_NAME.get(event, event)
        covered = name in spec.get("on", [])
    if not covered:
        return 0, "allow"
    kind = KINDS.get(spec.get("kind"))
    if kind is None:
        print(f"gate: unknown kind {spec.get('kind')!r}", file=sys.stderr)
        return 2, VERDICT_ERROR
    declared = spec.get("action", ACTION_BLOCK)
    if declared not in _ACTION_RANK:
        print(f"gate: unknown action {declared!r} (block, ask or warn)", file=sys.stderr)
        return 2, VERDICT_ERROR
    ctx = _context(event, spec, repo_root, push_stdin, base, head_ref, writes, added, own_paths(gate_path), session)
    if ctx is None:
        return 2, VERDICT_ERROR
    if event == "ci" and base and not ctx.rev_exists(base):
        print(
            f"gate: base ref {base!r} does not resolve -- refusing to scan an empty range. "
            "Fetch it (e.g. actions/checkout with fetch-depth: 0) or pass a base that exists.",
            file=sys.stderr,
        )
        return 2, VERDICT_ERROR
    signal = agent_signal(repo_root)
    judged = _judged_event(name, agent=signal is not None)
    result = kind(ctx, _params(gate_path, spec), judged)
    return Evaluation(spec, result, rollout(repo_root, event, signal, base), signal, judged)


def judge(
    gate_path: Path,
    event: str,
    push_stdin: str | None,
    repo_root: Path,
    base: str | None = None,
    head_ref: str | None = None,
    writes: Mapping[str, str] | None = None,
    added: Mapping[str, str] | None = None,
    session: Mapping[str, object] | None = None,
) -> tuple[int, str]:
    """Run a compiled gate: (exit code, verdict), the verdict being allow, block, ask, warn or error."""
    outcome = evaluate(gate_path, event, push_stdin, repo_root, base, head_ref, writes, added, session)
    if isinstance(outcome, tuple):
        return outcome
    if event == "ci":
        declared = outcome.spec.get("action", ACTION_BLOCK)
        verdict = _verdict(outcome.result, declared, outcome.level)
        _annotate_safely(outcome.result, verdict, _policy_id(gate_path), repo_root)
    return _conclude(gate_path, outcome.spec, event, outcome.judged, outcome.result, (outcome.signal, outcome.level))


def run(gate_path: Path, event: str, push_stdin: str | None, repo_root: Path, **options: Any) -> int:
    """Run a compiled gate and return its process exit code: 0 allow, 1 block, 2 cannot judge, 3 ask, 4 warn."""
    return judge(gate_path, event, push_stdin, repo_root, **options)[0]


def _conclude(
    gate_path: Path, spec: dict, event: str, judged: str, result: GateResult, actor: tuple[str | None, str]
) -> tuple[int, str]:
    """Log the outcome and act on it: (exit code, verdict), and the words in the channel this event has.

    `actor` is the agent marker (or None) and the rollout level in force.
    """
    signal, level = actor
    declared = spec.get("action", ACTION_BLOCK)
    verdict = _verdict(result, declared, level)
    held = _verdict(result, declared)
    policy_id = _policy_id(gate_path)
    answered = verdict == ACTION_ASK and event in _GIT_EVENTS and _ask_answered(policy_id, signal)
    extra = {**(_held_record(held, level) if held != verdict else {}), **_actor(signal)}
    if answered:
        extra["override"] = ALLOW_ENV
    _log_outcome(gate_path, judged, spec, result, "allow" if answered else verdict, extra)
    if held != verdict:
        print(_OBSERVE_NOTE.format(policy=policy_id or "gate", held=held), file=sys.stderr)
    if answered:
        print(f"gate: {policy_id} asked; allowed by {ALLOW_ENV}.", file=sys.stderr)
        return 0, "allow"
    if verdict == ACTION_BLOCK:
        _report_refusal(result, spec, judged, signal, policy_id)
        return 1, verdict
    if verdict == ACTION_ASK and event in _GIT_EVENTS:
        print(_reason(result, spec, judged, policy_id), file=sys.stderr)
        print(_ask_refusal(policy_id, signal), file=sys.stderr)
        return 1, verdict
    return (0 if verdict == "allow" else _deliver(verdict, result, spec, event, policy_id)), verdict

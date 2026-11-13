"""`chock check --floor` (preview): judge what a pull request will land with the base's gates, run by this engine.

base must be an ancestor of head (pass the merge result); everything comes from the tree diff base..head and
the commits in it. A changed control-plane path is listed (`floor/control-plane-changed`), never read for
meaning; the base's gates judge everything else and no head file executes.
Exit 0 clean, 1 any refusal (each naming its rule or policy and path), 2 undecided.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from chock.display import inert
from chock.gate.runner import (
    ACTION_ASK,
    ACTION_BLOCK,
    COMPILED_PREFIX,
    FLOOR_EVENT,
    KINDS,
    SCRIPT_BASE_GATE,
    GateResult,
    committed_rollout,
)
from chock.gate.runner.constants import _ACTION_RANK, _DEPENDENCY_KIND, _ROLLOUT_CEILING
from chock.gate.runner.context import ListingError
from chock.gate.runner.kinds import PatternDeadlineError
from chock.gate.runner.report import _reason
from chock.gate.runner.script import _UNDECIDED
from chock.validation import control_plane as cp
from chock.validation import floor_sarif
from chock.validation.floor_context import FloorContext
from chock.validation.floor_git import FloorError, Revision, changed_paths, require_ancestor, resolve, toplevel
from chock.validation.floor_history import history_findings
from chock.validation.floor_outcome import Outcome

EXIT_REFUSED, EXIT_UNDECIDED = 1, 2
_CI_GATE = "ci-gate/gate.json"
_SURFACES = ("ci-gate", "git-hook")
_SCRIPT, _DEPENDENCY, _REF = "script", _DEPENDENCY_KIND, "forbidden_ref"
_REFUSING = (ACTION_BLOCK, ACTION_ASK)
_FIRST_ADOPTION = "floor: base has no chock gates; nothing was judged"
_NO_GATES = "floor: the base has no compiled ci gates; no gate judged the content (the control-plane rule still ran)"
_CONTROL_PLANE = (
    "{rule} ({mode}): {count} path(s) -- these files define the guardrails; the floor does not judge "
    "whether a change to them is safe. A person decides."
)
_LISTED_GAP = "{rule}: under `listed` the content of these paths was not judged; code-owner review is the check"
_NOT_REQUIRED = (
    "floor (preview): a floor only where this check is a required status check the pull request cannot "
    "redefine; that is the repository's own setting, unverified by chock. It judges committed content only."
)


def _out(line: str) -> None:
    sys.stdout.write(line + "\n")


def _err(line: str) -> None:
    sys.stderr.write(line + "\n")


@dataclass(frozen=True)
class Gate:
    """One compiled ci gate as the base commits it."""

    policy: str
    rev: Revision
    path: str
    spec: dict


def base_gates(base: Revision) -> list[Gate]:
    found: list[Gate] = []
    for path in base.paths(COMPILED_PREFIX):
        policy, _, tail = path.removeprefix(COMPILED_PREFIX).partition("/")
        if tail != _CI_GATE:
            continue
        try:
            spec = json.loads(base.text(path) or "")
        except ValueError:
            spec = None
        found.append(Gate(policy, base, path, spec if isinstance(spec, dict) else {}))
    return found


def _relative(named: str) -> str:
    """`named` when it is a path inside the repository; FloorError (undecided) for an absolute or escaping one."""
    if not named or Path(named).is_absolute() or ".." in Path(named).parts or "\\" in named or ":" in named:
        msg = f"gate names {named!r}, which is not a path inside the repository"
        raise FloorError(msg)
    return named


def _params(gate: Gate, tree: Path) -> dict:
    """The gate's params, with every file it names taken from the base, materialised under `tree`."""
    params = dict(gate.spec.get("params") or {})
    if gate.spec.get("kind") == _SCRIPT:
        if gate.spec.get("script_base") == SCRIPT_BASE_GATE:
            folder = gate.path.rsplit("/", 1)[0]
            script = f"{folder}/{params.get('script', '')}"
        else:
            script = _relative(str(params.get("script", "")))
            folder = script.rsplit("/", 1)[0] if "/" in script else ""
        gate.rev.materialise(f"{folder}/" if folder else script, tree)
        params["script"] = str(tree / script)
    if gate.spec.get("kind") == _DEPENDENCY and params.get("allowlist_file"):
        named = _relative(str(params["allowlist_file"]))
        gate.rev.materialise(named, tree)
        params["allowlist_file"] = str(tree / named)
    return params


def _judge(gate: Gate, ctx: FloorContext, tree: Path) -> GateResult | str:
    """The gate's result, or why it could not judge."""
    spec, label = gate.spec, f"{gate.policy} [base]"
    kind = KINDS.get(spec.get("kind"))
    if not spec or kind is None or spec.get("action", ACTION_BLOCK) not in _ACTION_RANK:
        return f"{label}: unreadable gate, unknown kind or unknown action"
    if spec.get("kind") == _REF and not ctx.head_ref:
        return f"{label}: a branch gate needs --head-ref <branch under test>"
    try:
        result = kind(ctx, _params(gate, tree), FLOOR_EVENT)
    except (ListingError, PatternDeadlineError, FloorError) as exc:
        return f"{label}: {inert(str(exc))}"
    if not result.allowed and (result.message or "").endswith(_UNDECIDED):
        return f"{label}: {inert(result.message or '')}"  # could not judge: undecided whatever the rollout
    return result


def _verdict(result: GateResult, declared: str, level: str) -> str:
    if result.allowed:
        return "allow"
    return min(result.verdict or declared, declared, _ROLLOUT_CEILING[level], key=_ACTION_RANK.__getitem__)


def judge_gates(  # noqa: PLR0913 -- the range, the branch, what it excludes and the level
    repo: Path, base: Revision, head: Revision, head_ref: str | None, *, plane: cp.ControlPlane, level: str
) -> Outcome:
    """Run the base's ci gates over base..head; `ask` refuses, since nobody can be asked in CI.

    A gate that cannot judge is undecided before the rollout applies: `observe` softens refusals, never that.
    """
    outcome = Outcome()
    with tempfile.TemporaryDirectory(prefix="chock-floor-") as scratch:
        for gate in base_gates(base):
            if "commit" not in (gate.spec.get("on") or []) and gate.spec:
                continue
            ctx = FloorContext(
                repo, base=base, head=head, head_ref=head_ref, scope=gate.spec.get("paths"),
                control_plane=plane.covers,
            )  # fmt: skip
            result = _judge(gate, ctx, Path(scratch))
            if isinstance(result, str):
                outcome.undecided.append(result)
                continue
            verdict = _verdict(result, gate.spec.get("action", ACTION_BLOCK), level)
            if verdict == "allow":
                continue
            line = f"{gate.policy} [base] ({verdict}): {_reason(result, gate.spec, FLOOR_EVENT, gate.policy)}"
            (outcome.refusals if verdict in _REFUSING else outcome.notes).append(line)
    return outcome


def _declared(base: Revision, policy: str) -> str:
    """The strictest action the base's compiled gates of `policy` declare, on either surface."""
    actions = []
    for surface in _SURFACES:
        try:
            spec = json.loads(base.text(f"{COMPILED_PREFIX}{policy}/{surface}/gate.json") or "null")
        except ValueError:
            spec = None
        if isinstance(spec, dict) and spec.get("action", ACTION_BLOCK) in _ACTION_RANK:
            actions.append(spec.get("action", ACTION_BLOCK))
    return max(actions or [ACTION_BLOCK], key=_ACTION_RANK.__getitem__)


def _judged(repo: Path, base: Revision, head: Revision, branch: str | None) -> Outcome:
    plane = cp.through_links(cp.from_base(base), base, head)
    listed = [path for path in changed_paths(repo, base.sha, head.sha) if plane.covers(path)]
    level = committed_rollout(repo, base.sha)
    outcome = judge_gates(repo, base, head, branch, plane=plane, level=level)
    outcome.listed, outcome.mode, outcome.in_force = listed, plane.mode, plane.summary()
    if not base_gates(base):
        outcome.notes.append(_NO_GATES)
    try:
        history, notes = history_findings(repo, base, head, plane.covers)
    except FloorError as exc:
        history, notes = [], []
        outcome.undecided.append(inert(str(exc)))
    for policy, finding in history:
        verdict = min(_declared(base, policy), _ROLLOUT_CEILING[level], key=_ACTION_RANK.__getitem__)
        (outcome.refusals if verdict in _REFUSING else outcome.notes).append(
            f"{policy} [history] ({verdict}): {finding}"
        )
    outcome.notes += notes
    return outcome


def _print(outcome: Outcome) -> None:
    _out(outcome.in_force)
    if outcome.listed:
        head = "FAIL" if outcome.mode == cp.REFUSE else "LISTED"
        text = _CONTROL_PLANE.format(rule=cp.RULE, mode=outcome.mode, count=len(outcome.listed))
        _out(f"{head} {text}")
        for path in outcome.listed:
            _out(f"  {inert(path)}")
        if outcome.mode == cp.LISTED:
            _out(f"note: {_LISTED_GAP.format(rule=cp.RULE)}")
    for line in outcome.notes:
        _out(f"note: {line}")
    for line in outcome.refusals:
        _out(f"FAIL {line}")
    for line in outcome.undecided:
        _err(f"UNDECIDED {line}")
    _out(_NOT_REQUIRED)


def _code(outcome: Outcome) -> int:
    if outcome.undecided:
        return EXIT_UNDECIDED
    refused = outcome.refusals or (outcome.listed and outcome.mode == cp.REFUSE)
    return EXIT_REFUSED if refused else 0


def floor(repo: Path, base_ref: str, head_ref_rev: str, branch: str | None, sarif: str | None = None) -> int:
    repo = toplevel(repo)
    base_sha, head_sha = resolve(repo, base_ref, "base"), resolve(repo, head_ref_rev, "head")
    require_ancestor(repo, base_sha, head_sha)
    _out(f"== floor (preview): base {base_sha[:12]}, head {head_sha[:12]}")
    base, head = Revision(repo, base_sha), Revision(repo, head_sha)
    if not base.paths(".chock/"):
        _out(_FIRST_ADOPTION)
        return 0
    outcome = _judged(repo, base, head, branch)
    _print(outcome)
    code = _code(outcome)
    return floor_sarif.write(repo, sarif, outcome, code) if sarif else code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chock check --floor")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", required=True, help="The pull request's base: its gates, waivers and rules bind")
    parser.add_argument("--head", default="HEAD", help="The merge result under test, read as objects only")
    parser.add_argument("--head-ref", default=None, help="The branch under test, for branch gates")
    parser.add_argument("--sarif", default=None, help="Also write the result as SARIF 2.1.0 to this file")
    args = parser.parse_args(argv)
    try:
        return floor(Path(args.repo), args.base, args.head, args.head_ref, args.sarif)
    except FloorError as exc:
        _err(f"UNDECIDED floor: {inert(str(exc))}")
    except Exception as exc:  # noqa: BLE001 -- 1 means refused; anything undecided is 2, naming only the type
        _err(f"UNDECIDED floor: no verdict was established ({type(exc).__name__})")
    return EXIT_UNDECIDED

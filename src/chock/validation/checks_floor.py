"""`chock check --floor`: judge a pull request with the base's gates, run by this engine; no head file executes.

Exit 0 clean, 1 any refusal (each naming its policy or tamper rule and path), 2 undecided.
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
    POLICIES_PREFIX,
    SCRIPT_BASE_GATE,
    GateResult,
    committed_rollout,
)
from chock.gate.runner.constants import _ACTION_RANK, _DEPENDENCY_KIND, _ROLLOUT_CEILING
from chock.gate.runner.context import ListingError
from chock.gate.runner.kinds import PatternDeadlineError
from chock.gate.runner.report import _reason
from chock.gate.runner.script import _UNDECIDED
from chock.validation.floor_context import FloorContext
from chock.validation.floor_git import FloorError, Revision, merge_base, resolve
from chock.validation.floor_history import history_findings
from chock.validation.tamper import Revs, pack_notes, packs_changed, tamper
from chock.validation.tamper_hooks import not_covered

EXIT_REFUSED, EXIT_UNDECIDED = 1, 2
_CI_GATE = "ci-gate/gate.json"
_SCRIPT, _DEPENDENCY, _REF = "script", _DEPENDENCY_KIND, "forbidden_ref"
_REFUSING = (ACTION_BLOCK, ACTION_ASK)
_NO_GATES = "floor: the base has no compiled gates; no gate judged this pull request (tamper rules still ran)"
_NOT_COVERED = "floor/hook-switches not covered: {} -- the keys that switch their hooks off are not verified here"
_NOT_REQUIRED = (
    "floor: a floor only where this check is a required status check; that is the repository's own "
    "setting, unverified by chock. It judges committed content only."
)


def _out(line: str) -> None:
    sys.stdout.write(line + "\n")


def _err(line: str) -> None:
    sys.stderr.write(line + "\n")


@dataclass(frozen=True)
class Gate:
    """One compiled ci gate as one revision commits it."""

    policy: str
    source: str
    rev: Revision
    path: str
    spec: dict


@dataclass
class Outcome:
    refusals: list[str]
    undecided: list[str]
    notes: list[str]


def _gates(rev: Revision, source: str) -> dict[str, Gate]:
    found: dict[str, Gate] = {}
    for path in rev.paths(COMPILED_PREFIX):
        rest = path.removeprefix(COMPILED_PREFIX)
        policy, _, tail = rest.partition("/")
        if tail != _CI_GATE:
            continue
        try:
            spec = json.loads(rev.text(path) or "")
        except ValueError:
            spec = None
        found[policy] = Gate(policy, source, rev, path, spec if isinstance(spec, dict) else {})
    return found


def policy_set(base: Revision, head: Revision) -> tuple[list[Gate], list[str]]:
    """Every base gate, plus each head gate that is new or differs (both run; the stricter binds).

    A head script gate is new code and is never run here: the base set binds until it merges.
    """
    at_base, at_head = _gates(base, "base"), _gates(head, "head")
    run = list(at_base.values())
    notes: list[str] = []
    for policy, gate in sorted(at_head.items()):
        same = policy in at_base and base.text(at_base[policy].path) == head.text(gate.path)
        if same:
            continue
        if gate.spec.get("kind") == _SCRIPT:
            notes.append(f"{policy} [head]: not judged at floor (new script code, runs after merge)")
        else:
            run.append(gate)
    return run, notes


def _relative(named: str) -> str:
    """`named` when it is a path inside the repository; FloorError (undecided) for an absolute or escaping one."""
    if not named or Path(named).is_absolute() or ".." in Path(named).parts or "\\" in named or ":" in named:
        msg = f"gate names {named!r}, which is not a path inside the repository"
        raise FloorError(msg)
    return named


def _params(gate: Gate, tree: Path) -> dict:
    """The gate's params, with every file it names taken from the gate's own revision, materialised under `tree`."""
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


def _own(gate: Gate, packs: frozenset[str]) -> tuple[str, ...]:
    """The policy's source folder, and only for a pack whose lock entry the pull request changed (listed in a
    `floor/pack-changed` note); otherwise a gate judges its own folders like any other file."""
    return (f"{POLICIES_PREFIX}{gate.policy}/",) if gate.policy in packs else ()


def _judge(  # noqa: PLR0913, PLR0917 -- the gate, where it runs, what changed
    gate: Gate, repo: Path, revs: tuple[str, str, str], head_ref: str | None, tree: Path, packs: frozenset[str]
) -> GateResult | str:
    """The gate's result, or why it could not judge."""
    spec, label = gate.spec, f"{gate.policy} [{gate.source}]"
    kind = KINDS.get(spec.get("kind"))
    if not spec or kind is None or spec.get("action", ACTION_BLOCK) not in _ACTION_RANK:
        return f"{label}: unreadable gate, unknown kind or unknown action"
    if spec.get("kind") == _REF and not head_ref:
        return f"{label}: a branch gate needs --head-ref <branch under test>"
    base, head, fork = revs
    ctx = FloorContext(
        repo, base=base, head=head, merge_base=fork, head_ref=head_ref, scope=spec.get("paths"), own=_own(gate, packs)
    )
    try:
        result = kind(ctx, _params(gate, tree / gate.source), FLOOR_EVENT)
    except (ListingError, PatternDeadlineError, FloorError) as exc:
        return f"{label}: {inert(str(exc))}"
    if not result.allowed and (result.message or "").endswith(_UNDECIDED):
        return f"{label}: {inert(result.message or '')}"  # could not judge: undecided whatever the rollout
    return result


def _verdict(result: GateResult, declared: str, level: str) -> str:
    if result.allowed:
        return "allow"
    return min(result.verdict or declared, declared, _ROLLOUT_CEILING[level], key=_ACTION_RANK.__getitem__)


def judge_gates(  # noqa: PLR0913, PLR0917 -- the range, the branch and the changed packs
    repo: Path, base: Revision, head: Revision, fork: str, head_ref: str | None, packs: frozenset[str] = frozenset()
) -> Outcome:
    """Run the policy set over base...head; `ask` refuses, since nobody can be asked in CI.

    A gate that cannot judge is undecided before the rollout applies: `observe` softens refusals, never that.
    """
    gates, notes = policy_set(base, head)
    outcome = Outcome([], [], notes)
    level = committed_rollout(repo, base.sha)
    with tempfile.TemporaryDirectory(prefix="chock-floor-") as scratch:
        for gate in gates:
            if "commit" not in (gate.spec.get("on") or []) and gate.spec:
                continue
            result = _judge(gate, repo, (base.sha, head.sha, fork), head_ref, Path(scratch), packs)
            if isinstance(result, str):
                outcome.undecided.append(result)
                continue
            verdict = _verdict(result, gate.spec.get("action", ACTION_BLOCK), level)
            if verdict == "allow":
                continue
            reason = _reason(result, gate.spec, FLOOR_EVENT, gate.policy)
            line = f"{gate.policy} [{gate.source}] ({verdict}): {reason}"
            (outcome.refusals if verdict in _REFUSING else outcome.notes).append(line)
    return outcome


def floor(repo: Path, base_ref: str, head_ref_rev: str, branch: str | None) -> int:
    repo = repo.resolve()
    base_sha, head_sha = resolve(repo, base_ref, "base"), resolve(repo, head_ref_rev, "head")
    fork = merge_base(repo, base_sha, head_sha)
    base, head = Revision(repo, base_sha), Revision(repo, head_sha)
    revs = Revs(base, Revision(repo, fork), head)
    _out(f"== floor: base {base_sha[:12]}, head {head_sha[:12]}, merge-base {fork[:12]}")
    packs = packs_changed(revs)
    outcome = judge_gates(repo, base, head, fork, branch, packs)
    if not base.paths(COMPILED_PREFIX):
        outcome.notes.append(_NO_GATES)
    tampered = [t.render() for t in tamper(revs, packs)]
    try:
        history, history_notes = history_findings(repo, base, head, fork, packs)
    except FloorError as exc:
        history, history_notes = [], []
        outcome.undecided.append(inert(str(exc)))
    uncovered = not_covered(revs)
    history_notes += pack_notes(revs, packs) + ([_NOT_COVERED.format(", ".join(uncovered))] if uncovered else [])
    for line in outcome.notes + history_notes:
        _out(f"note: {line}")
    refusals = outcome.refusals + tampered + history
    for line in refusals:
        _out(f"FAIL {line}")
    for line in outcome.undecided:
        _err(f"UNDECIDED {line}")
    _out(_NOT_REQUIRED)
    if outcome.undecided:
        return EXIT_UNDECIDED
    return EXIT_REFUSED if refusals else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chock check --floor")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", required=True, help="The pull request's base: its gates, waivers and rules bind")
    parser.add_argument("--head", default="HEAD", help="The commit under test, read as objects only")
    parser.add_argument("--head-ref", default=None, help="The branch under test, for branch gates")
    args = parser.parse_args(argv)
    try:
        return floor(Path(args.repo), args.base, args.head, args.head_ref)
    except FloorError as exc:
        _err(f"floor: {inert(str(exc))}")
    except Exception as exc:  # noqa: BLE001 -- 1 means refused; anything undecided is 2, naming only the type
        _err(f"floor: no verdict was established ({type(exc).__name__})")
    return EXIT_UNDECIDED

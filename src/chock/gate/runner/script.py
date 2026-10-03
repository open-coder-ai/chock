"""Gate runner: the `script` kind -- a policy's own program, its exit code and findings document."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from ..budget import ENGINE_BUDGET_SECONDS
from .context import GateContext, GateResult

# >>> gate.py 07
#: A script gate's budget to answer. Past it the script has not decided, and an undecided
#: gate refuses.
_SCRIPT_TIMEOUT_SECONDS = ENGINE_BUDGET_SECONDS

#: The exit codes a script gate speaks, the command-guard contract's: 0 allows, 1 blocks, 3 asks,
#: 4 warns. Anything else is not a verdict. The gate's declared action caps what a script may choose.
_SCRIPT_ALLOW, _SCRIPT_BLOCK, _SCRIPT_ASK, _SCRIPT_WARN = 0, 1, 3, 4

#: Interpreter-crash signatures, lower-cased: exit 1 with one of these, or with no words at all,
#: is a script that failed, not one that refused.
_CRASH_MARKERS = ("traceback (most recent call last)", "syntax error", "syntaxerror", "unexpected eof")

_UNDECIDED = " -- refusing rather than allowing what it never judged"

_FINDINGS_KEY = "findings"


def _spawn(script: Path, ctx: GateContext, payload: dict, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- the script is the policy's own, named in its manifest
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ctx.repo_root,
        timeout=timeout,
        check=False,
    )


def _is_finding(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    line = item.get("line")
    return (
        isinstance(item.get("key"), str)
        and isinstance(item.get("path"), str)
        and isinstance(line, int)
        and not isinstance(line, bool)
        and isinstance(item.get("message"), str)
        and isinstance(item.get("new", False), bool)
    )


def _findings_document(stdout: str) -> list[dict] | None:
    """The findings a script printed as its one JSON object, or None when stdout is not that document."""
    try:
        document = json.loads(stdout)
    except ValueError:
        return None
    found = document.get(_FINDINGS_KEY) if isinstance(document, dict) else None
    if not isinstance(found, list) or not all(_is_finding(item) for item in found):
        return None
    return found


#: A finding's optional `rule`: a short label, so a code fragment never reaches the log through it.
_RULE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._:/-]{0,63}")


def _rule_ids(findings: list[dict]) -> dict[str, int]:
    """Findings per declared rule id; a finding with no valid `rule` is not counted."""
    declared = (item.get("rule") for item in findings)
    return dict(Counter(rule for rule in declared if isinstance(rule, str) and _RULE_ID_RE.fullmatch(rule)))


def _new_findings(found: list[dict], baseline: list[dict]) -> list[dict]:
    """The findings the baseline does not account for: per path and key, each baseline copy absolves one."""
    unspent = Counter((item["path"], item["key"]) for item in baseline)
    fresh: list[dict] = []
    for item in found:
        slot = (item["path"], item["key"])
        if item.get("new") or not unspent[slot]:
            fresh.append(item)
        else:
            unspent[slot] -= 1
    return fresh


def _baseline_findings(ctx: GateContext, script: Path, material: dict, started: float) -> list[dict]:
    """What the script finds in the baseline text of the change's files; empty when it cannot say.

    A new file has no baseline and is left out. A run that fails, times out, prints no findings
    document, or has no budget left contributes nothing, which errs toward blocking.
    """
    texts = {path: text for path in material["writes"] if (text := ctx.head_blob(path))}
    remaining = _SCRIPT_TIMEOUT_SECONDS - (time.monotonic() - started)
    if not texts or remaining <= 0:
        return []
    try:
        proc = _spawn(script, ctx, {**material, "writes": texts, "baseline": True}, remaining)
    except (subprocess.TimeoutExpired, OSError):
        return []
    return _findings_document(proc.stdout or "") or []


def _exit_verdict(script: Path, proc: subprocess.CompletedProcess[str]) -> GateResult:
    """The verdict of a script's exit code alone, with its own words as the reason."""
    spoken = ((proc.stderr or "") + (proc.stdout or "")).strip()
    if proc.returncode == _SCRIPT_ALLOW:
        return GateResult(allowed=True)
    if proc.returncode == _SCRIPT_BLOCK:
        if not spoken or any(marker in spoken.lower() for marker in _CRASH_MARKERS):
            first = spoken.splitlines()[0] if spoken else "no reason given"
            return GateResult(allowed=False, message=f"script gate: {script.name} crashed ({first}){_UNDECIDED}")
        return GateResult(allowed=False, message=spoken)
    if proc.returncode in (_SCRIPT_ASK, _SCRIPT_WARN):
        word = "ask" if proc.returncode == _SCRIPT_ASK else "warn"
        return GateResult(allowed=False, message=spoken or f"{script.name} chose to {word}", verdict=word)
    first = spoken.splitlines()[0] if spoken else ""
    detail = f": {first}" if first else ""
    return GateResult(allowed=False, message=f"script gate: {script.name} exited {proc.returncode}{detail}{_UNDECIDED}")


def _judge_findings(
    ctx: GateContext, script: Path, material: dict, proc: subprocess.CompletedProcess[str], started: float
) -> GateResult:
    """Judge only the findings the change introduces; the change-run's exit code is the verdict for them."""
    if proc.returncode not in (_SCRIPT_ALLOW, _SCRIPT_BLOCK, _SCRIPT_ASK, _SCRIPT_WARN):
        # A document followed by a crash or an unknown exit is undecided, never a clean pass.
        return _exit_verdict(script, proc)
    found = _findings_document(proc.stdout or "") or []
    if not found:
        return GateResult(allowed=True, detail={"new_findings": 0, "baseline_findings": 0})
    baseline = _baseline_findings(ctx, script, material, started)
    fresh = _new_findings(found, baseline)
    counts = {"new_findings": len(fresh), "baseline_findings": len(baseline)}
    if not fresh or proc.returncode == _SCRIPT_ALLOW:
        return GateResult(allowed=True, detail=counts)
    lines = [f"{item['path']}:{item['line']}: {item['message']}" for item in fresh]
    verdict = {_SCRIPT_ASK: "ask", _SCRIPT_WARN: "warn"}.get(proc.returncode, "")
    return GateResult(
        allowed=False, matches=lines, verdict=verdict, detail=counts, rules=_rule_ids(fresh), findings=fresh
    )


def _kind_script(ctx: GateContext, params: dict, event: str) -> GateResult:
    """Hand the material to the policy's own script and carry back its verdict.

    The script reads `{"event", "repo_root", "writes": {path: text}}` on stdin -- the staged
    blobs at commit and push, the write itself at tool use and at the turn's end -- so one
    script serves every surface the declarative kinds do, and reads them the same way. It
    answers with an exit code: 0 allows; 1 refuses, 3 asks, 4 warns, with its own words on stderr.
    A missing script, a crash or a timeout is undecided, and an undecided gate takes its declared
    action, in this runner's words: a gate that cannot reach a decision never reports an allow it
    never established.

    A script that also prints a findings document (`{"findings": [...]}`) is run once more on
    the baseline text, and only the findings the change adds are judged (see spec/gate-dsl.md).
    """
    named = str(params.get("script", ""))
    script = ctx.repo_root / named
    if not script.is_file():
        return GateResult(allowed=False, message=f"script gate: {named!r} is not installed{_UNDECIDED}")
    writes = {path: ctx.staged_blob(path) for path in ctx.staged_paths()}
    if not writes:
        return GateResult(allowed=True)
    material = {"event": event, "repo_root": str(ctx.repo_root), "writes": writes}
    if ctx.session:
        material["session"] = ctx.session
    started = time.monotonic()
    try:
        proc = _spawn(script, ctx, material, _SCRIPT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        budget = f"gave no verdict within {_SCRIPT_TIMEOUT_SECONDS}s"
        return GateResult(allowed=False, message=f"script gate: {script.name} {budget}{_UNDECIDED}")
    except OSError as exc:
        return GateResult(allowed=False, message=f"script gate: {script.name} could not run ({exc}){_UNDECIDED}")
    if _findings_document(proc.stdout or "") is None:
        return _exit_verdict(script, proc)
    return _judge_findings(ctx, script, material, proc, started)

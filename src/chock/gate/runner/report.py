"""Gate runner: refusal text, CI-inert output, and GitHub Actions annotations and step summary."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .constants import (
    _AGENT_COMMIT_NOTE,
    ACTION_BLOCK,
    AGENT_COMMIT_EVENT,
    HEAD_WAIVER_EVENTS,
    TOOL_USE_EVENT,
)
from .context import GateResult

# >>> gate.py 15
#: One sentence that tells the reader to write a `chock: allow` waiver: an agent's waiver is never honoured.
_WAIVER_SENTENCE_RE = re.compile(r"(?:(?<=\.\s)|^)(?:(?!\.\s)[^\n])*?chock: allow(?:(?!\.\s)[^\n])*\.?", re.MULTILINE)
_AGENT_WAIVER_HINT = "If this must stay, ask a person to review it; an agent cannot add the waiver."
_CUSTOMISE_POINTER = (
    "A person customises this policy's rules in .agents/policies/{policy}/manifest.yaml; an agent cannot loosen them."
)


def _for_agent(text: str) -> str:
    """The text with any waiver instruction replaced by the agent's way forward."""
    return _WAIVER_SENTENCE_RE.sub(_AGENT_WAIVER_HINT, text)


def _summary(result: GateResult, policy_id: str | None) -> str:
    """One line saying how many new findings the gate refused on."""
    return (
        f"{policy_id or 'gate'} refused {len(result.matches)} new finding(s) (only lines this change adds are judged)."
    )


def _reason(result: GateResult, spec: dict, event: str = "commit", policy_id: str | None = None) -> str:
    """The refusal. A findings gate puts its findings first; at tool use the agent gets them alone."""
    agent = event in HEAD_WAIVER_EVENTS
    policy = result.message or spec.get("message", "")
    matches = list(result.matches)
    if agent:
        policy, matches = _for_agent(policy), [_for_agent(m) for m in matches]
    if "new_findings" not in result.detail:
        return "\n".join([policy, *(f"  - {m}" for m in matches)])
    if event == TOOL_USE_EVENT:
        return "\n".join([*matches, _CUSTOMISE_POINTER.format(policy=policy_id or "<id>")])
    return "\n".join([*matches, _summary(result, policy_id), policy])


def _report_refusal(result: GateResult, spec: dict, judged: str, signal: str | None, policy_id: str | None) -> None:
    reason = _reason(result, spec, judged, policy_id)
    print(_encodable(ci_inert(reason) if judged == "ci" else reason, sys.stderr), file=sys.stderr)
    if judged == AGENT_COMMIT_EVENT and signal:
        print(_AGENT_COMMIT_NOTE.format(signal=signal), file=sys.stderr)


def _annotation(policy_id: str | None, reason: str) -> str:
    """A GitHub Actions `::warning::` workflow command; the runner reads it from stdout."""
    title = _escape_property(f"chock {policy_id or 'gate'}")
    return f"::warning title={title}::{_escape_data(reason)}"


#: GitHub shows at most this many error and this many warning annotations per step.
_ANNOTATION_CAP = 10
_GITHUB_ACTIONS_ENV = "GITHUB_ACTIONS"
_STEP_SUMMARY_ENV = "GITHUB_STEP_SUMMARY"


def _github_actions() -> bool:
    return os.environ.get(_GITHUB_ACTIONS_ENV) == "true"


def _escape_data(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(text: str) -> str:
    return _escape_data(text).replace(":", "%3A").replace(",", "%2C")


def _cell(value: object) -> str:
    """Text that stays inside one markdown table cell or bullet, whatever a finding holds: no new row,
    no HTML, and no link, image or mention (a finding's text comes from the pull request)."""
    text = " ".join(str(value).split())
    for char in "\\|[]!@":
        text = text.replace(char, "\\" + char)
    return text.replace("`", "'").replace("<", "&lt;")


_LINE_BREAK = re.compile(r"\r\n|\r|\n")


def ci_inert(text: str) -> str:
    """`text` with no line a GitHub runner would parse as a workflow command.

    The runner reads commands from stdout and stderr alike, a line at a time (CR, LF or CRLF), after
    trimming it. A finding's path or message comes from the pull request, so at ci a line that would
    start with `::` is prefixed; every other line is printed as it was.
    """
    lines = _LINE_BREAK.split(text)
    return "\n".join(f"> {line}" if line.strip().startswith("::") else line for line in lines)


def _encodable(text: str, stream: Any) -> str:
    """`text` as `stream` can write it: a lone surrogate or a character its encoding lacks becomes `?`."""
    encoding = getattr(stream, "encoding", None) or "utf-8"
    return text.encode(encoding, "replace").decode(encoding, "replace")


def _repo_relative(path: str, repo_root: Path) -> str:
    """The finding's path as a repo-relative, forward-slash path; empty when it is outside the repo."""
    text = path.replace("\\", "/")
    if text.startswith("/") or re.match(r"[A-Za-z]:/", text):
        try:
            text = Path(text).resolve().relative_to(repo_root.resolve()).as_posix()
        except (ValueError, OSError):
            return ""
    parts = [part for part in text.split("/") if part not in ("", ".")]
    return "" if ".." in parts else "/".join(parts)


def _workflow_command(level: str, finding: dict, policy_id: str | None, repo_root: Path) -> str:
    """One `::error` or `::warning` command for a finding; every untrusted part is escaped."""
    rule = finding.get("rule")
    title = f"chock {policy_id or 'gate'}" + (f": {rule}" if isinstance(rule, str) and rule else "")
    props = []
    if path := _repo_relative(finding["path"], repo_root):
        props.append(f"file={_escape_property(path)}")
        if finding["line"] > 0:
            props.append(f"line={finding['line']}")
    props.append(f"title={_escape_property(title)}")
    return f"::{level} {','.join(props)}::{_escape_data(finding['message'])}"


#: What names one step of one job attempt: every gate the step runs shares its annotation budget.
_STEP_KEYS = ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "GITHUB_ACTION")


def _budget_file() -> Path | None:
    """This step's annotation budget under `RUNNER_TEMP`, or None off a runner (each gate then caps alone)."""
    temp = os.environ.get("RUNNER_TEMP")
    if not temp:
        return None
    key = "-".join(re.sub(r"[^A-Za-z0-9_.-]", "_", os.environ.get(name, "")) for name in _STEP_KEYS)
    return Path(temp) / f"chock-annotations-{key}.json"


def _take_budget(level: str, wanted: int) -> int:
    """How many of `wanted` annotations of `level` this gate may print, and record them as spent.

    A budget that cannot be read or written prints none: the step summary still lists every finding.
    """
    path = _budget_file()
    if path is None:
        return min(wanted, _ANNOTATION_CAP)
    try:
        spent = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        used = spent.get(level, 0) if isinstance(spent, dict) else _ANNOTATION_CAP
        used = used if isinstance(used, int) and not isinstance(used, bool) and used >= 0 else _ANNOTATION_CAP
        take = max(0, min(wanted, _ANNOTATION_CAP - used))
        path.write_text(json.dumps({**spent, level: used + take}), encoding="utf-8")
    except (OSError, ValueError):
        return 0
    return take


def _annotation_plan(findings: list[dict], level: str) -> tuple[list[dict], list[dict]]:
    """The findings to annotate within this step's budget and those left out, ordered by path then line."""
    ordered = sorted(findings, key=lambda item: (item["path"], item["line"], item["key"]))
    take = _take_budget(level, len(ordered)) if ordered else 0
    return ordered[:take], ordered[take:]


def _step_summary(result: GateResult, policy_id: str | None, verdict: str, overflow: list[dict]) -> str:
    """The markdown appended to the step summary: the gate's row, then any findings past the cap."""
    counts = result.detail
    lines = [
        "### Chock gate",
        "",
        "| policy | new findings | baseline | verdict |",
        "|---|---|---|---|",
        f"| {_cell(policy_id or 'gate')} | {counts['new_findings']} | {counts['baseline_findings']} | {verdict} |",
    ]
    if overflow:
        lines += ["", f"#### Not annotated ({len(overflow)}: GitHub shows 10 errors and 10 warnings per step)", ""]
        for item in overflow:
            rule = f"[{_cell(item['rule'])}] " if isinstance(item.get("rule"), str) and item["rule"] else ""
            lines.append(f"- {_cell(item['path'])}:{item['line']}: {rule}{_cell(item['message'])}")
    return "\n".join(lines) + "\n"


def _annotate(result: GateResult, verdict: str, policy_id: str | None, repo_root: Path) -> None:
    """On GitHub Actions, print one workflow command per new finding and append the step summary.

    Output only: nothing here reads or changes a verdict or exit code.
    """
    if not _github_actions() or "new_findings" not in result.detail:
        return
    level = "error" if verdict == ACTION_BLOCK else "warning"
    shown: list[dict] = []
    overflow: list[dict] = []
    if verdict != "allow":
        shown, overflow = _annotation_plan(result.findings, level)
    for item in shown:
        print(_encodable(_workflow_command(level, item, policy_id, repo_root), sys.stdout))
    summary = os.environ.get(_STEP_SUMMARY_ENV)
    if summary:
        try:
            with open(summary, "a", encoding="utf-8", errors="replace") as handle:
                handle.write(_step_summary(result, policy_id, verdict, overflow))
        except OSError as exc:
            print(f"gate: cannot write the step summary: {exc}", file=sys.stderr)


def _annotate_safely(result: GateResult, verdict: str, policy_id: str | None, repo_root: Path) -> None:
    """`_annotate`, whose failure is reported and never reaches the verdict, the refusal or the log."""
    try:
        _annotate(result, verdict, policy_id, repo_root)
    except Exception as exc:  # noqa: BLE001 -- output only: an annotation failure never changes the verdict
        print(f"gate: GitHub annotations skipped: {type(exc).__name__}", file=sys.stderr)

"""`chock check --floor --sarif <file>`: the floor's result as one SARIF 2.1.0 log; the exit code is unchanged."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from chock import __version__
from chock.gate.sarif import INFORMATION_URI, SARIF_SCHEMA, safe_text
from chock.gate.sarif_output import write_output
from chock.validation import control_plane as cp
from chock.validation.floor_outcome import Outcome

_REFUSED = "floor/refused"
_UNDECIDED_EXIT = 2


def _result(rule: str, level: str, text: str, path: str | None = None) -> dict:
    result: dict = {"ruleId": rule, "level": level, "message": {"text": safe_text(text)}}
    if path is not None:
        result["locations"] = [{"physicalLocation": {"artifactLocation": {"uri": safe_text(path)}}}]
    return result


def log(outcome: Outcome) -> dict:
    """Control-plane paths first, one result each; then every refusal; undecided lines as notifications."""
    level = "error" if outcome.mode == cp.REFUSE else "note"
    why = f"control-plane path changed ({outcome.mode}); the floor does not judge whether this is safe"
    results = [_result(cp.RULE, level, why, path) for path in outcome.listed]
    results += [_result(_REFUSED, "error", line) for line in outcome.refusals]
    notes = [{"level": "error", "message": {"text": safe_text(line)}} for line in outcome.undecided]
    driver = {"name": "chock", "version": __version__, "informationUri": INFORMATION_URI}
    run = {
        "tool": {"driver": driver},
        "invocations": [{"executionSuccessful": not outcome.undecided, "toolExecutionNotifications": notes}],
        "results": results,
    }
    return {"$schema": SARIF_SCHEMA, "version": "2.1.0", "runs": [run]}


def write(repo: Path, output: str, outcome: Outcome, code: int) -> int:
    """Write the log; `code` stands unless the file cannot be written, which is undecided."""
    text = json.dumps(log(outcome), indent=2) + "\n"
    if failure := write_output(Path(output), text, repo):
        sys.stderr.write(f"UNDECIDED floor: cannot write --sarif: {failure}\n")
        return _UNDECIDED_EXIT
    return code

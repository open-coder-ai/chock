"""`chock incident` output: plain text and Markdown made inert, and ASCII JSON."""

from __future__ import annotations

import json
from typing import Any

from chock.gate.runner.report import _cell as md_cell
from chock.gate.runner.report import inert
from chock.resources import package_data_dir

DATA: dict[str, str] = json.loads(
    package_data_dir("chock", "data").joinpath("incident.json").read_text(encoding="utf-8")
)
#: A plain allowed tool call: counted per session, never listed or put to a policy (GAP-2b).
ALLOWED = "allowed"


def chain_line(found: dict[str, Any]) -> str:
    """One log's chain within the window: intact from seq X to Y, or each break's file:line."""
    if found["breaks"]:
        text = "; ".join(f"break at {b['file']}:{b['line']} ({b['kind']})" for b in found["breaks"])
    elif found["seqs"]:
        text = f"chain intact from seq {min(found['seqs'])} to {max(found['seqs'])}"
    else:
        text = "no chained record in the window"
    if found["outside"]:
        text += f"; {found['outside']} break(s) outside the window (chock status --verify-log)"
    return f"{found['log']}: {text}"


def _counts(session: dict[str, Any]) -> list[tuple[str, object]]:
    verdicts = sorted(session.get("verdicts", {}).items())
    return [("allowed calls", session[ALLOWED]), *verdicts, ("overrides", session.get("overrides", 0))]


def _fields(entry: dict[str, Any]) -> list[tuple[str, object]]:
    return [(k, v) for k, v in entry.items() if k not in ("ts", "kind", "at")]


def _header(timeline: Any) -> list[str]:
    window = f"{timeline.since} to {timeline.until or 'now'} (UTC; the start is included, the end is not)"
    privacy = DATA["share_notice"] if timeline.share else DATA["local_notice"]
    return [window, DATA["notice"], privacy, "Logs read: " + (", ".join(timeline.logs) or "no decision log found")]


def render_text(timeline: Any) -> str:
    """Plain text; every value from the log is made inert before it reaches a terminal."""
    lines = ["chock incident: " + inert(_header(timeline)[0]), *map(inert, _header(timeline)[1:]), ""]
    lines.append(f"Timeline ({len(timeline.entries)} entries)")
    for e in timeline.entries:
        fields = "  ".join(f"{k}={inert(v)}" for k, v in _fields(e))
        lines.append(f"  {inert(e['ts'] or 'unknown time')}  {e['kind']}  {fields}  ({inert(e['at'])})")
    lines += ["  nothing in this window"] if not timeline.entries else []
    lines += ["", "Sessions"]
    for sid, s in timeline.sessions.items():
        actors = ",".join(s["actors"]) or "-"
        counts = "  ".join(f"{k}={v}" for k, v in _counts(s))
        lines.append(inert(f"  {sid}  {s['first']} to {s['last']}  actor={actors}  {counts}"))
    lines += ["", "Chain", *(inert("  " + chain_line(c)) for c in timeline.chains)]
    lines += [f"{timeline.omitted} debug line(s) left out"] if timeline.omitted else []
    return "\n".join(lines) + "\n"


def render_md(timeline: Any) -> str:
    """Markdown; every value from the log stays inside its cell or bullet, inert."""
    head = _header(timeline)
    lines = [
        "# Incident timeline",
        "",
        *(f"- {md_cell(h)}" for h in head),
        "",
        f"## Timeline ({len(timeline.entries)} entries)",
    ]
    for e in timeline.entries:
        fields = "; ".join(f"{k} = {md_cell(v)}" for k, v in _fields(e))
        lines.append(f"- {md_cell(e['ts'] or 'unknown time')} **{e['kind']}** {fields} ({md_cell(e['at'])})")
    lines += ["- nothing in this window"] if not timeline.entries else []
    lines += ["", "## Sessions", "", "| session | first | last | actor | counts |", "| --- | --- | --- | --- | --- |"]
    for sid, s in timeline.sessions.items():
        cells = [
            sid,
            s["first"],
            s["last"],
            ", ".join(s["actors"]) or "-",
            ", ".join(f"{k} {v}" for k, v in _counts(s)),
        ]
        lines.append("| " + " | ".join(md_cell(c) for c in cells) + " |")
    lines += ["", "## Chain", *(f"- {md_cell(chain_line(c))}" for c in timeline.chains)]
    return "\n".join(lines) + "\n"


def render_json(timeline: Any) -> str:
    """JSON (ASCII only: a control character is written as an escape, never raw)."""
    doc = {
        "format": DATA["format"],
        "since": timeline.since,
        "until": timeline.until,
        "notice": DATA["notice"],
        "shared": timeline.share,
        "logs": timeline.logs,
        "timeline": timeline.entries,
        "sessions": timeline.sessions,
        "chains": [{"log": c["log"], "summary": chain_line(c), "breaks": c["breaks"]} for c in timeline.chains],
        "debug_lines_left_out": timeline.omitted,
    }
    return json.dumps(doc, indent=2, ensure_ascii=True, default=dict) + "\n"


RENDER = {"text": render_text, "md": render_md, "json": render_json}

"""Rendering for `chock status --only log --by`: the grouped table, headlines and markdown."""

from __future__ import annotations

from typing import Any

_COLUMNS = (
    ("events", "events"),
    ("block", "blocked"),
    ("ask", "asked"),
    ("warn", "warned"),
    ("would_block", "would-block"),
    ("new_findings", "new"),
    ("baseline_findings", "baseline"),
)


def _columns(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """The would-block column appears only once a record carries the field."""
    return [c for c in _COLUMNS if c[0] != "would_block" or any(r["would_block"] for r in rows)]


def headline(row: dict[str, Any]) -> str:
    """`java-security: 14 would-block (9 path traversal, 5 SQL) across 3 agents`."""
    counts = [f"{row[key]} {label}" for key, label in _COLUMNS[1:5] if row[key]] or ["0 blocked"]
    text = f"{row['group']}: {', '.join(counts)}"
    if row["rules"]:
        text += f" ({', '.join(f'{n} {rule}' for rule, n in row['rules'].items())})"
    if row["agents"]:
        text += f" across {len(row['agents'])} agent{'s' if len(row['agents']) != 1 else ''}"
    if row["files"]:
        text += "; top files: " + ", ".join(f"{f['path']} ({f['count']})" for f in row["files"])
    return text


def render_groups_text(rows: list[dict[str, Any]], by: str) -> str:
    if not rows:
        return "No gate outcomes recorded yet."
    columns = _columns(rows)
    width = max(len(by), *(len(str(r["group"])) for r in rows))
    head = by.ljust(width) + "".join(f"  {label:>{max(len(label), 5)}}" for _, label in columns)
    lines = [head]
    for row in rows:
        cells = "".join(f"  {row[key]:>{max(len(label), 5)}}" for key, label in columns)
        lines.append(str(row["group"]).ljust(width) + cells)
    return "\n".join([*lines, "", *(headline(r) for r in rows)])


def _cell(value: Any) -> str:
    """Text that stays inside one markdown table cell or bullet, whatever a log line holds.

    The log is writable by whatever runs in the repo, so a value cannot open a link or image either.
    """
    text = _printable(" ".join(str(value).split()))
    for char in "\\|[]":
        text = text.replace(char, "\\" + char)
    return text.replace("`", "'").replace("<", "&lt;")


def _printable(text: str) -> str:
    """Drop control characters (terminal escape sequences) that a log line may carry."""
    return "".join(c if c.isprintable() or c == "\n" else "?" for c in text)


def render_groups_md(rows: list[dict[str, Any]], by: str, since: int | None = None) -> str:
    window = f" (last {since} days)" if since is not None else ""
    title = f"### Chock gate log by {by}{window}"
    if not rows:
        return f"{title}\n\nNo gate outcomes recorded yet."
    columns = _columns(rows)
    lines = [
        title,
        "",
        f"| {by} | " + " | ".join(label for _, label in columns) + " |",
        "|" + "---|" * (len(columns) + 1),
    ]
    for row in rows:
        lines.append(f"| {_cell(row['group'])} | " + " | ".join(str(row[key]) for key, _ in columns) + " |")
    return "\n".join([*lines, "", *(f"- {_cell(headline(r))}" for r in rows)])

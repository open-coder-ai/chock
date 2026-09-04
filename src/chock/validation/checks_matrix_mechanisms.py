"""T2: verify enforcement-matrix.md rows against the code they claim, not just their presence.

For every row that names a mechanism, checks three things: the named function is defined
somewhere in `src/`, it is actually invoked on at least one of chock's two dispatch paths
(`chock validate` via `validation/engine.py`, `chock check` via `lifecycle.py`), and it can
emit the severity the row claims (a function that only ever constructs `"warning"` findings
cannot back a row that claims `error`). A row whose Severity column is `eval` or
`unautomated` is skipped -- knowingly, surfaced as an `info` finding, not silently.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from chock.validation.matrix_callgraph import (
    CallGraph,
    build_call_graph,
    load_modules,
    reachable_modules,
    verify_mechanism,
)
from chock.validation.report import Finding, Report, emit

_ENTRY_MODULES = ("chock.validation.engine", "chock.lifecycle")
_SKIPPED_SEVERITIES = frozenset({"eval", "unautomated"})
_CATEGORY = "matrix_mechanism"

#: `spec/enforcement-matrix.md`, relative to a repo root. `lifecycle.py` imports this rather
#: than writing its own copy, so the path literal exists in exactly one place (chock's own
#: repeated-literal check flags a string repeated 3+ times).
MATRIX_RELATIVE_PATH = Path("spec") / "enforcement-matrix.md"

_ROW_ID_RE = re.compile(r"^[A-Z]{2,4}-\d+$")
_MECHANISM_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)\(\)`")
#: A row splits into at least this many `|`-delimited parts to reach ID, Check, and Severity.
_MATRIX_ROW_MIN_COLUMNS = 5
#: Splits a table row on unescaped `|` only, so a literal `\|` inside a cell (e.g. `verify\|block`)
#: stays in the cell instead of being read as a column boundary.
_UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")


@dataclass(frozen=True)
class MatrixRow:
    row_id: str
    check_text: str
    severity: str


def parse_matrix_rows(matrix_file: Path) -> list[MatrixRow]:
    """Parse `| ID | Spec | Check | Severity | Notes |` rows, skipping the header/divider."""
    rows: list[MatrixRow] = []
    for line in matrix_file.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        parts = [p.strip() for p in _UNESCAPED_PIPE_RE.split(line)]
        if len(parts) < _MATRIX_ROW_MIN_COLUMNS or not _ROW_ID_RE.match(parts[1]):
            continue
        rows.append(MatrixRow(row_id=parts[1], check_text=parts[3], severity=parts[4].lower()))
    return rows


def extract_mechanisms(check_text: str) -> list[str]:
    """Pull `` `name()` `` function references out of a row's Check column."""
    return _MECHANISM_RE.findall(check_text)


@dataclass(frozen=True)
class _CheckContext:
    matrix_file: Path
    report: Report
    graph: CallGraph
    reachable: set[str]


def _check_mechanism(ctx: _CheckContext, row: MatrixRow, name: str) -> None:
    verdict = verify_mechanism(ctx.graph, ctx.reachable, name)
    ref = str(ctx.matrix_file)
    if not verdict.exists:
        ctx.report.add(Finding(ref, _CATEGORY, "error", f"{row.row_id}: `{name}()` is not defined anywhere in src/."))
    elif not verdict.invoked:
        ctx.report.add(
            Finding(
                ref,
                _CATEGORY,
                "error",
                f"{row.row_id}: `{name}()` exists but is not invoked on the engine.py or lifecycle.py dispatch path.",
            )
        )
    elif row.severity not in verdict.achievable:
        achievable_str = ", ".join(sorted(verdict.achievable)) or "nothing"
        ctx.report.add(
            Finding(
                ref,
                _CATEGORY,
                "error",
                f"{row.row_id}: `{name}()` cannot emit severity '{row.severity}' (can emit: {achievable_str}).",
            )
        )


def _check_row(ctx: _CheckContext, row: MatrixRow) -> None:
    if row.severity in _SKIPPED_SEVERITIES:
        ctx.report.add(
            Finding(str(ctx.matrix_file), _CATEGORY, "info", f"{row.row_id}: unautomated, skipped knowingly.")
        )
        return

    mechanisms = extract_mechanisms(row.check_text)
    if not mechanisms:
        ctx.report.add(
            Finding(
                str(ctx.matrix_file),
                _CATEGORY,
                "error",
                f"{row.row_id}: names no `function()` mechanism and Severity is not `eval`/`unautomated`.",
            )
        )
        return

    for name in mechanisms:
        _check_mechanism(ctx, row, name)


def check_matrix_mechanisms(root: Path, report: Report) -> None:
    """T2: for every matrix row naming a mechanism, verify it exists, runs, and can fail as claimed."""
    matrix_file = root / MATRIX_RELATIVE_PATH
    if not matrix_file.exists():
        return

    modules = load_modules(root / "src")
    reachable = reachable_modules(modules, _ENTRY_MODULES)
    graph = build_call_graph(modules)
    ctx = _CheckContext(matrix_file, report, graph, reachable)
    for row in parse_matrix_rows(matrix_file):
        _check_row(ctx, row)


USAGE = """usage: chock check --only mechanisms

For every spec/enforcement-matrix.md row naming a `function()` mechanism, verify it is
defined in src/, invoked on the engine.py or lifecycle.py dispatch path, and can emit the
severity the row claims. Rows marked `eval`/`unautomated` are skipped, not silently.
"""


def main(argv: list[str] | None = None) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE.strip())  # noqa: T201 -- --help output, same convention as authoring/matrix.py
        return 0

    parser = argparse.ArgumentParser(prog="chock check --only mechanisms")
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args(argv)

    report = Report()
    check_matrix_mechanisms(Path(args.repo).resolve(), report)
    emit(report, use_json=args.json)
    return 0 if report.is_clean() else 1


if __name__ == "__main__":
    raise SystemExit(main())

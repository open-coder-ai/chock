"""The hook-latency harness: its self-test runs and its config and report shapes load."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import bench_hooks

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def test_self_test_runs_against_stub_hooks() -> None:
    """`--self-test` times sleeping stub hooks and exits 0; it measures nothing about chock."""
    done = subprocess.run(
        [sys.executable, str(TOOLS / "bench_hooks.py"), "--self-test"], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("self-test ok")


def test_config_loads_with_both_events() -> None:
    """The JSON beside the harness names policies and a Bash and a Write payload."""
    cfg = bench_hooks.load_config(TOOLS / "bench_hooks.json")
    assert cfg["policies"]
    assert set(cfg["events"]) == {"Bash", "Write"}
    for spec in cfg["events"].values():
        json.dumps(spec["payload"])


def test_markdown_has_a_row_per_engine_tool_and_order() -> None:
    """The summary table lists every engine, tool and order it was given."""
    stat = {"median_ms": 1.0, "p90_ms": 2.0, "min_ms": 0.5, "max_ms": 3.0, "n": 4}
    report = [
        {"engine": e, "results": {"Bash": {"hooks": 6, "sequential": stat, "parallel": stat}}} for e in ("a", "b")
    ]
    assert len(bench_hooks.markdown(report).splitlines()) == 2 + 4

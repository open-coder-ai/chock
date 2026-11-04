"""The hook-latency harness: its self-test runs and its config and report shapes load."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import bench_hooks
import pytest

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


def _repo_with_failing_hook(root: Path) -> Path:
    """A stub adopter repo whose one PreToolUse hook writes `boom` to stderr and exits 3."""
    (root / ".claude").mkdir()
    command = f'"{sys.executable}" -c "import sys; sys.stderr.write(\'boom\'); sys.exit(3)"'
    settings = {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": command}]}]}}
    (root / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    return root


def test_a_failing_hook_makes_the_run_invalid(tmp_path: Path) -> None:
    """A non-zero exit on a clean payload is an error naming the hook and its stderr, never a fast sample."""
    repo = _repo_with_failing_hook(tmp_path)
    cfg = bench_hooks.load_config(TOOLS / "bench_hooks.json")
    with pytest.raises(bench_hooks.HookFailedError, match=r"exited 3.*boom"):
        bench_hooks.measure(repo, cfg, 1)


def test_the_command_line_exits_non_zero_on_a_failing_hook(tmp_path: Path) -> None:
    """The harness process fails, so the workflow job fails, when a hook fails."""
    repo = _repo_with_failing_hook(tmp_path)
    argv = [sys.executable, str(TOOLS / "bench_hooks.py"), "--repo", str(repo), "--n", "1"]
    done = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert done.returncode != 0
    assert "boom" in done.stderr

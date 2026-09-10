"""A guard implementation may be Python, not only shell -- discovery, execution, evals, packaging."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from chock.compile.emitters.in_agent import GUARD_SUFFIXES, _guard_script
from chock.eval.suites import Policy
from chock.gate.guard_runner import GUARD_BLOCKED, GUARD_CLEAN, find_interpreter, run_guard
from chock.plugin.claude import claude_plugin_files

POLICY_ID = "refuse-widget"

_GUARD_SOURCE = '''#!/usr/bin/env python3
"""Block any command mentioning the widget; the argv contract is the shell one."""

import sys

if any("widget" in a for a in sys.argv[1:]):
    print("widget commands are refused", file=sys.stderr)
    raise SystemExit(1)
raise SystemExit(0)
'''

_MANIFEST = {
    "id": POLICY_ID,
    "name": "Refuse Widget",
    "version": "0.0.1",
    "description": "trigger: widget commands. avoid: running them.",
    "artifact": "rule",
    "enforcement": "advise",
    "rule": {"text": "block(widget): any_command\nprefer: the supported path\n"},
}


def _policy(tmp_path: Path, suffix: str, *, source: str = _GUARD_SOURCE) -> Path:
    policy_dir = tmp_path / ".agents" / "policies" / POLICY_ID
    (policy_dir / "implementations").mkdir(parents=True)
    (policy_dir / "manifest.yaml").write_text(yaml.safe_dump(_MANIFEST), encoding="utf-8")
    (policy_dir / "implementations" / f"{POLICY_ID}{suffix}").write_text(source, encoding="utf-8")
    return policy_dir


def test_discovery_finds_a_python_guard(tmp_path: Path) -> None:
    """Without this a .py implementation is invisible: never wired, never packaged."""
    assert _guard_script(_policy(tmp_path, ".py"), POLICY_ID) == f"{POLICY_ID}.py"


def test_shell_wins_when_a_policy_ships_both(tmp_path: Path) -> None:
    """Discovery order is fixed, so which guard runs never depends on filesystem order."""
    policy_dir = _policy(tmp_path, ".py")
    (policy_dir / "implementations" / f"{POLICY_ID}.sh").write_text("exit 0\n", encoding="utf-8")
    assert _guard_script(policy_dir, POLICY_ID) == f"{POLICY_ID}.sh"
    assert GUARD_SUFFIXES.index(".sh") < GUARD_SUFFIXES.index(".py")


def test_interpreter_follows_the_suffix(tmp_path: Path) -> None:
    """A .py guard handed to bash would fail; the suffix picks the interpreter."""
    assert find_interpreter(Path("x/implementations/p.py")) == sys.executable
    shell = find_interpreter(_policy(tmp_path, ".sh", source="exit 0\n") / "implementations" / f"{POLICY_ID}.sh")
    assert shell is None or "bash" in shell


def test_a_python_guard_blocks_and_allows(tmp_path: Path) -> None:
    """End-to-end: the runner executes it and reads its exit code as a verdict."""
    guard = _policy(tmp_path, ".py") / "implementations" / f"{POLICY_ID}.py"
    assert run_guard(guard, "make widget") == GUARD_BLOCKED
    assert run_guard(guard, "make gadget") == GUARD_CLEAN


def test_a_python_guard_makes_the_suite_deterministic(tmp_path: Path) -> None:
    """A shipped guard the eval runner cannot see would silently demote the policy to tier 3."""
    policy_dir = _policy(tmp_path, ".py")
    suite = Policy(POLICY_ID, policy_dir, _MANIFEST)
    assert [p.name for p in suite.guards] == [f"{POLICY_ID}.py"]
    assert suite.deterministic


def test_the_plugin_packages_the_python_guard(tmp_path: Path) -> None:
    """The packaged plugin is what other clients read, so the guard must reach it verbatim."""
    policy_dir = _policy(tmp_path, ".py")
    files = claude_plugin_files(policy_dir, _MANIFEST, tmp_path)
    packaged = {p.as_posix(): body for p, body in files.items()}
    guard_rel = next(rel for rel in packaged if rel.endswith(f"{POLICY_ID}.py"))
    assert packaged[guard_rel] == _GUARD_SOURCE
    assert any(rel.endswith("hooks.json") for rel in packaged), "a shipped guard must be wired"

"""A Stop that names several workspace roots and no `cwd` (Cursor) checks every root inside a repository.

From the BV-E4 review: the turn-end gate used to check only the first root, so a finding in the second
ended the turn unseen.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import init_repo
from test_cursor_windows_root import PAYLOADS, WORKFLOW, _hook, _run, gate_policy
from test_plugin_gate import _manifest
from test_stop_reentry import SECRET, SPEC

from chock.gate import stop_roots, write_gate
from chock.gate.assemble import runner_source
from chock.plugin import cursor

_ = gate_policy  # a fixture, used by name


@pytest.fixture
def gate(tmp_path: Path) -> Path:
    """A plugin's packaged gate, its runner beside it: no compiled layout, so the root comes from the event."""
    path = tmp_path / "plugin" / "leaky" / "scripts" / "gate.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(SPEC), encoding="utf-8")
    (path.parent / "gate.py").write_text(runner_source(), encoding="utf-8")
    return path


def _repo(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir()
    return init_repo(path)


def _leak(repo: Path) -> None:
    (repo / "leak.py").write_text(f'key = "{SECRET}"\n', encoding="utf-8")


def _stop(gate: Path, *roots: Path, cwd: Path | None = None):
    raw = {"session_id": "s1", "loop_count": 0, "workspace_roots": [str(r) for r in roots]}
    event = SimpleNamespace(event="stop", raw=raw, cwd=str(cwd) if cwd else None, path=None)
    return write_gate.evaluate_gate(["--gate", str(gate)], event)


def test_a_finding_in_the_second_root_refuses_the_stop(gate: Path, tmp_path: Path) -> None:
    first, second = _repo(tmp_path, "first"), _repo(tmp_path, "second")
    assert _stop(gate, first, second) is None
    _leak(second)
    verdict, message = _stop(gate, first, second)
    assert verdict == write_gate.VERDICT_DENY
    assert f"In {second}:" in message and f"In {first}:" not in message


def test_each_root_reports_its_own_findings(gate: Path, tmp_path: Path) -> None:
    first, second = _repo(tmp_path, "first"), _repo(tmp_path, "second")
    _leak(first)
    _leak(second)
    _verdict, message = _stop(gate, first, second)
    assert message.index(f"In {first}:") < message.index(f"In {second}:")
    assert message.count("leak.py") >= 2, message


def test_only_roots_inside_a_repository_are_checked_once_per_repository(gate: Path, tmp_path: Path) -> None:
    plain, repo = tmp_path / "plain", _repo(tmp_path, "repo")
    plain.mkdir()
    (repo / "sub").mkdir()
    event = SimpleNamespace(raw={"workspace_roots": [str(plain), str(repo), str(repo / "sub")]}, cwd=None)
    assert stop_roots.stop_roots(event, plain) == [repo]
    _leak(repo)
    assert _stop(gate, plain, repo, repo / "sub")[0] == write_gate.VERDICT_DENY


def test_a_cwd_is_checked_beside_every_root(gate: Path, tmp_path: Path) -> None:
    first, second = _repo(tmp_path, "first"), _repo(tmp_path, "second")
    _leak(second)
    assert _stop(gate, first, second, cwd=first)[0] == write_gate.VERDICT_DENY
    assert _stop(gate, cwd=second)[0] == write_gate.VERDICT_DENY
    assert _stop(gate, cwd=first) is None


def test_a_built_cursor_plugin_refuses_a_stop_on_a_finding_in_the_second_root(gate_policy, tmp_path: Path) -> None:
    """The vendored runtime, its Stop hook started outside both roots: the unpinned action in the second refuses."""
    manifest = _manifest(kind="content_regex")
    manifest["hook"]["gate"]["params"] = {"content_pattern": r"uses: [\w./-]+@v\d"}
    out = tmp_path / "dist" / "cursor" / manifest["id"]
    cursor.build_cursor_plugin(gate_policy(manifest), manifest, tmp_path, out)
    first, second = _repo(tmp_path, "first"), _repo(tmp_path, "second")
    stop = {**PAYLOADS["stop"], "loop_count": 0, "workspace_roots": [str(first), str(second)]}
    clean = _run(_hook(out, "stop"), out, tmp_path, stop)
    assert (clean.returncode, "followup_message" in clean.stdout) == (0, False), clean
    (second / ".github" / "workflows").mkdir(parents=True)
    (second / ".github" / "workflows" / "w.yml").write_text(WORKFLOW, encoding="utf-8")
    answer = json.loads(_run(_hook(out, "stop"), out, tmp_path, stop).stdout)
    assert f"In {second}:" in answer["followup_message"], answer
    assert ".github/workflows/w.yml" in answer["followup_message"]

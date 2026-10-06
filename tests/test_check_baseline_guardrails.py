"""`chock check --only baseline` reports a guardrail switched off in `.chock/guardrails.json` as a loosening."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from chock.validation.checks_baseline import main
from chock.validation.guardrails_baseline import GUARDRAILS, switched_off

B, P = "chock-guardrails", "block-destructive-commands"


def _file(states: dict[str, str] | None = None, bundle: str = B) -> str:
    return json.dumps({"version": 1, "bundles": {bundle: states or {}}})


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo(tmp_path: Path, text: str | None) -> Path:
    repo = tmp_path / "repo"
    (repo / ".chock").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@e")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    if text is not None:
        (repo / GUARDRAILS.filename).write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    return repo


@pytest.mark.parametrize(
    ("base", "head", "found"),
    [
        (None, _file({P: "off"}), [f"{B}/{P}: on -> off"]),
        (_file({P: "on"}), _file({P: "off"}), [f"{B}/{P}: on -> off"]),
        (_file(), _file({P: "off", "other-one": "on"}), [f"{B}/{P}: on -> off"]),
        ("{broken", _file({P: "off"}), [f"{B}/{P}: on -> off"]),
        (_file({P: "off"}), _file({P: "off"}), []),
        (_file({P: "off"}), _file({P: "on"}), []),
        (_file({P: "off"}), "{broken", []),
        (None, None, []),
        (_file({P: "on"}), None, [GUARDRAILS.fallback]),
    ],
)
def test_what_counts_as_switched_off(base: str | None, head: str | None, found: list[str]) -> None:
    assert switched_off(base, head) == found


def test_a_branch_that_switches_a_guardrail_off_fails(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = _repo(tmp_path, None)
    (repo / GUARDRAILS.filename).write_text(_file({P: "off"}), encoding="utf-8")
    assert main(["--repo", str(repo), "--base", "main"]) == 1
    out = capsys.readouterr().out
    assert f"{B}/{P}: on -> off" in out and "looser than main" in out


def test_a_branch_that_switches_one_back_on_passes(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _file({P: "off"}))
    (repo / GUARDRAILS.filename).write_text(_file({P: "on"}), encoding="utf-8")
    assert main(["--repo", str(repo), "--base", "main"]) == 0


def test_a_linked_toggle_file_cannot_be_compared_and_fails(tmp_path: Path) -> None:
    repo = _repo(tmp_path, None)
    (tmp_path / "elsewhere.json").write_text(_file({P: "off"}), encoding="utf-8")
    (repo / GUARDRAILS.filename).symlink_to(tmp_path / "elsewhere.json")
    assert main(["--repo", str(repo), "--base", "main"]) == 1

"""Scaffold tests: new policies are declarative by default and validate clean."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from chock.scaffold import new

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
PYTHONPATH = str(FRAMEWORK_ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")


class _FixedDateTime:
    @classmethod
    def now(cls, tz: timezone) -> datetime:
        return datetime(2026, 8, 3, 12, 0, tzinfo=tz)


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = PYTHONPATH
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, env=env)


def _init(repo: Path) -> Path:
    repo.mkdir()
    _run([sys.executable, "-m", "chock.cli", "init", str(repo), "--skip-hooks"], repo)
    return repo


def test_new_policy_scaffolds_declarative_gate(tmp_path: Path) -> None:
    """`new policy` produces a manifest with hook.gate, no gate.yaml, and passes validate."""
    repo = _init(tmp_path / "r")
    _run([sys.executable, "-m", "chock.cli", "new", "policy", "demo-gate"], repo)

    policy_dir = repo / ".agents" / "policies" / "demo-gate"
    assert not (policy_dir / "gate.yaml").exists()
    assert not (policy_dir / "implementations").exists()

    manifest = (policy_dir / "manifest.yaml").read_text(encoding="utf-8")
    assert "hook:" in manifest
    assert "kind: content_regex" in manifest
    assert "runner: declarative" not in manifest

    result = _run([sys.executable, "-m", "chock.cli", "validate", str(repo)], repo)
    assert result.returncode == 0, result.stdout + result.stderr


def _template_copy(tmp_path: Path) -> Path:
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    source = new._templates_dir()
    for filename in ("manifest.yaml.tmpl", "eval-suite.yaml.tmpl", "SKILL.md.tmpl", "subagent.yaml.tmpl"):
        (template_dir / filename).write_bytes((source / filename).read_bytes())
    return template_dir


def test_new_renders_packaged_templates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each generated artifact is the corresponding package template after substitution."""
    monkeypatch.setattr(new, "datetime", _FixedDateTime)
    template_dir = _template_copy(tmp_path)
    monkeypatch.setattr(new, "_templates_dir", lambda: template_dir)

    policy_root = tmp_path / "policy"
    skill_root = tmp_path / "skill"
    subagent_root = tmp_path / "subagent"
    new._new_policy("demo-policy", policy_root)
    new._new_skill("demo-skill", skill_root)
    new._new_subagent("demo-subagent", subagent_root)

    values = {
        "id": "demo-policy",
        "name": "Demo Policy",
        "now": "2026-08-03T12:00:00+00:00",
        "date": "2026-08-03",
    }
    assert (policy_root / ".agents/policies/demo-policy/manifest.yaml").read_text() == (
        (template_dir / "manifest.yaml.tmpl").read_text().format(**values)
    )
    assert (policy_root / ".agents/policies/demo-policy/evals/suite.yaml").read_text() == (
        (template_dir / "eval-suite.yaml.tmpl").read_text().format(**values)
    )
    assert (skill_root / ".agents/skills/demo-skill/SKILL.md").read_text() == (
        (template_dir / "SKILL.md.tmpl").read_text().format(id="demo-skill", name="Demo Skill")
    )
    assert (subagent_root / ".agents/skills/demo-subagent/subagent.yaml").read_text() == (
        (template_dir / "subagent.yaml.tmpl")
        .read_text()
        .format(id="demo-subagent", name="Demo Subagent", now="2026-08-03T12:00:00+00:00")
    )


def test_editing_template_changes_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The generator reads the template at invocation time rather than using a copy."""
    template_dir = _template_copy(tmp_path)
    monkeypatch.setattr(new, "_templates_dir", lambda: template_dir)
    template_path = template_dir / "SKILL.md.tmpl"
    original = template_path.read_text()
    template_path.write_text(original.replace("TODO: fill in skill documentation.", "LIVE TEMPLATE EDIT."))

    new._new_skill("live-edit", tmp_path / "out")

    assert "LIVE TEMPLATE EDIT." in (tmp_path / "out/.agents/skills/live-edit/SKILL.md").read_text()


def test_missing_template_is_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    template_dir = _template_copy(tmp_path)
    (template_dir / "SKILL.md.tmpl").unlink()
    monkeypatch.setattr(new, "_templates_dir", lambda: template_dir)

    assert new.cmd_new(["skill", "missing-template", "--root", str(tmp_path / "out")]) == 2
    captured = capsys.readouterr()
    assert "SKILL.md.tmpl" in captured.err
    assert "Unable to read template" in captured.err
    assert "Traceback" not in captured.err

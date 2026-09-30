"""A policy's own words and files ride in its skill, in both package formats.

`skill/body.md` joins the rendered `SKILL.md` after the constraint block; every other file
under `skill/` is copied beside it. A guided setup page can then live where the skill that
opens it lives, and a change to either is drift the check sees.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from test_plugin_gate import GATE_SCRIPT, HELPER, POLICY_ID, SCRIPT, _build, _manifest

from chock.plugin.build import build_plugin, plugin_differences
from chock.plugin.claude import build_claude_plugin, claude_plugin_differences


@pytest.fixture
def gate_policy(tmp_path: Path):
    """A script-gate policy, optionally carrying a `skill/` folder."""

    def _make(manifest: dict, *, skill_files: dict[str, str] | None = None) -> Path:
        pack = tmp_path / ".agents" / "policies" / manifest["id"]
        (pack / "implementations").mkdir(parents=True)
        (pack / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
        (pack / "implementations" / SCRIPT).write_text(GATE_SCRIPT, encoding="utf-8")
        (pack / "implementations" / "helper.py").write_text(HELPER, encoding="utf-8")
        for rel, text in (skill_files or {}).items():
            dest = pack / "skill" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
        return pack

    return _make


BODY = "## Guided setup\n\nOpen `setup.html` beside this file."
PAGE = "<!doctype html><title>setup</title>"


def test_skill_body_and_assets_ride_in_both_package_formats(gate_policy, tmp_path: Path) -> None:
    manifest = _manifest()
    pack = gate_policy(manifest, skill_files={"body.md": BODY, "setup.html": PAGE, "references/contract.json": "{}"})

    build_plugin(pack, manifest, tmp_path)
    skill = (pack / "skills" / POLICY_ID / "SKILL.md").read_text(encoding="utf-8")
    assert BODY in skill
    assert skill.index("```\n\n" + BODY) < skill.index("This skill is advisory")
    assert (pack / "skills" / POLICY_ID / "setup.html").read_text(encoding="utf-8") == PAGE
    assert (pack / "skills" / POLICY_ID / "references" / "contract.json").exists()
    assert not (pack / "skills" / POLICY_ID / "body.md").exists()
    assert plugin_differences(pack, manifest, tmp_path) == []

    out = _build(pack, manifest, tmp_path)
    assert (out / "skills" / POLICY_ID / "setup.html").read_text(encoding="utf-8") == PAGE
    assert BODY in (out / "skills" / POLICY_ID / "SKILL.md").read_text(encoding="utf-8")


def test_a_changed_or_removed_asset_is_drift_and_a_rebuild_removes_it(gate_policy, tmp_path: Path) -> None:
    manifest = _manifest()
    pack = gate_policy(manifest, skill_files={"setup.html": PAGE})
    out = _build(pack, manifest, tmp_path)
    (pack / "skill" / "setup.html").write_text(PAGE + "<!-- v2 -->", encoding="utf-8")
    assert any("setup.html" in d for d in claude_plugin_differences(pack, manifest, tmp_path, out))
    (pack / "skill" / "setup.html").unlink()
    assert any("setup.html" in d for d in claude_plugin_differences(pack, manifest, tmp_path, out))
    build_claude_plugin(pack, manifest, tmp_path, out)
    assert not (out / "skills" / POLICY_ID / "setup.html").exists()


def test_a_policy_without_a_skill_folder_renders_exactly_as_before(gate_policy, tmp_path: Path) -> None:
    manifest = _manifest()
    pack = gate_policy(manifest)
    build_plugin(pack, manifest, tmp_path)
    skill = (pack / "skills" / POLICY_ID / "SKILL.md").read_text(encoding="utf-8")
    assert skill.endswith(
        "```\n\nThis skill is advisory: the client reading it has no mechanism to enforce it. The same policy compiled by `chock` blocks at commit, on an agent's file writes and at turn end. See https://github.com/open-coder-ai/chock\n"
    )

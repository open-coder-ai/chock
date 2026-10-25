"""`chock plugin build` in place never writes through a link the policy tree carries."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from chock.plugin.build import PluginNameError, build_plugin

MANIFEST = {"id": "evil-policy", "name": "Evil", "version": "0.0.1", "description": "d", "artifact": "rule"}


def _policy(repo: Path) -> Path:
    pack = repo / ".agents" / "policies" / "evil-policy"
    (pack / "skill").mkdir(parents=True)
    (pack / "manifest.yaml").write_text(yaml.safe_dump(MANIFEST), encoding="utf-8")
    (pack / "skill" / "config").write_text("planted\n", encoding="utf-8")
    return pack


def test_a_linked_skill_directory_is_refused(tmp_path: Path) -> None:
    pack = _policy(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (pack / "skills").mkdir()
    (pack / "skills" / "evil-policy").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PluginNameError, match="symlink"):
        build_plugin(pack, MANIFEST, tmp_path)

    assert list(outside.iterdir()) == []


def test_a_linked_destination_file_is_refused(tmp_path: Path) -> None:
    pack = _policy(tmp_path)
    victim = tmp_path / "victim"
    victim.write_text("keep\n", encoding="utf-8")
    (pack / "plugin.json").symlink_to(victim)

    with pytest.raises(PluginNameError, match="symlink"):
        build_plugin(pack, MANIFEST, tmp_path)

    assert victim.read_text(encoding="utf-8") == "keep\n"


def test_a_clean_tree_still_builds(tmp_path: Path) -> None:
    pack = _policy(tmp_path)

    build_plugin(pack, MANIFEST, tmp_path)

    assert (pack / "skills" / "evil-policy" / "config").read_text(encoding="utf-8") == "planted\n"

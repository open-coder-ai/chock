"""INDEX.md builder and rendering tests."""

from __future__ import annotations

from pathlib import Path

import yaml

from chock.index.builder import build_entries, max_tokens_for
from chock.index.render import render_index


def _write_policy(tmp_path: Path, policy_id: str, artifact: str, enforcement: str, **extra) -> None:
    dir_ = tmp_path / ".agents" / "policies" / policy_id
    dir_.mkdir(parents=True)
    data = {
        "id": policy_id,
        "name": policy_id.replace("-", " ").title(),
        "version": "0.1.0",
        "description": f"Description for {policy_id}.",
        "artifact": artifact,
        "enforcement": enforcement,
        "provenance": {"author": "x", "license": "Apache-2.0", "trust_tier": "sandbox"},
    }
    data.update(extra)
    (dir_ / "manifest.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def test_ordering_prioritizes_enforcement_not_id(tmp_path: Path) -> None:
    """A z-prefixed block rule must render before an a-prefixed advise rule."""
    _write_policy(tmp_path, "zzz-block", "rule", "block", rule={"text": "never: bad"})
    _write_policy(tmp_path, "aaa-advise", "rule", "advise", rule={"text": "prefer: good"})

    entries, _ = build_entries(tmp_path)
    output = render_index(entries, 2000)
    main = output.main

    z_pos = main.index("zzz-block")
    a_pos = main.index("aaa-advise")
    assert z_pos < a_pos, f"block rule should appear before advise rule (z={z_pos}, a={a_pos})"


def test_rendering_is_byte_identical_across_runs(tmp_path: Path) -> None:
    _write_policy(tmp_path, "p1", "rule", "block", rule={"text": "rule one"})
    _write_policy(tmp_path, "p2", "rule", "advise", rule={"text": "rule two"})

    entries1, _ = build_entries(tmp_path)
    out1 = render_index(entries1, 2000).main

    entries2, _ = build_entries(tmp_path)
    out2 = render_index(entries2, 2000).main

    assert out1 == out2


def test_malformed_folder_is_skipped_with_warning(tmp_path: Path) -> None:
    _write_policy(tmp_path, "good", "rule", "advise", rule={"text": "ok"})
    bad = tmp_path / ".agents" / "policies" / "bad"
    bad.mkdir(parents=True)
    (bad / "manifest.yaml").write_text("bad: [", encoding="utf-8")

    entries, warnings = build_entries(tmp_path)
    assert all(e.id != "bad" for e in entries)
    assert any("manifest_parse" in w for w in warnings)


def test_disabled_policies_are_absent(tmp_path: Path) -> None:
    _write_policy(tmp_path, "enabled", "rule", "advise", rule={"text": "ok"})
    _write_policy(tmp_path, "disabled", "rule", "advise", rule={"text": "nope"})

    config_dir = tmp_path / ".chock"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        yaml.safe_dump({"policies": {"disabled": ["disabled"]}}),
        encoding="utf-8",
    )

    entries, _ = build_entries(tmp_path)
    ids = {e.id for e in entries}
    assert "enabled" in ids
    assert "disabled" not in ids


def test_rules_carry_full_text_skills_are_summarized(tmp_path: Path) -> None:
    _write_policy(tmp_path, "the-rule", "rule", "advise", rule={"text": "line one\nline two\n"})
    _write_policy(tmp_path, "the-skill", "skill", "advise")

    entries, _ = build_entries(tmp_path)
    output = render_index(entries, 2000).main

    assert "line one" in output
    assert "line two" in output
    assert "the-skill" in output
    assert ".agents/policies/the-skill/manifest.yaml" in output


def test_default_max_tokens_without_config(tmp_path: Path) -> None:
    assert max_tokens_for(tmp_path) == 2000


def test_multiline_rule_text_keeps_its_line_structure(tmp_path: Path) -> None:
    """Each line of a rule is an independent directive and must stay on its own line."""
    _write_policy(
        tmp_path,
        "two-liner",
        "rule",
        "advise",
        rule={"text": "before(edit): read(file)\nnever(skip): verification"},
    )

    entries, _ = build_entries(tmp_path)
    main = render_index(entries, 2000).main

    assert "before(edit): read(file)\n" in main
    assert "  never(skip): verification" in main
    assert "read(file) never(skip)" not in main


def test_single_line_rule_stays_inline(tmp_path: Path) -> None:
    """One-line rules keep the compact form so the index does not grow for nothing."""
    _write_policy(tmp_path, "one-liner", "rule", "advise", rule={"text": "prefer: good"})

    entries, _ = build_entries(tmp_path)
    main = render_index(entries, 2000).main

    assert "- **one-liner**: prefer: good" in main

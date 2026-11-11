"""README's numbers, agent lists and repo table are derive.py's output from data.json and chock's own data."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
ASSETS = ROOT / "docs" / "assets" / "readme"
BLOCK_NAMES = {"numbers", "incidents", "plugins", "repo_agents", "faq_agents", "repos"}


def _derive():
    spec = importlib.util.spec_from_file_location("readme_derive", ASSETS / "derive.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _data() -> dict:
    return json.loads((ASSETS / "data.json").read_text(encoding="utf-8"))


def test_readme_blocks_match_their_sources() -> None:
    derive = _derive()
    text = README.read_text(encoding="utf-8")
    assert {m.group("name") for m in derive.BLOCK.finditer(text)} == BLOCK_NAMES
    assert derive.render_readme(text, _data()) == text, (
        "README.md differs from its sources; run: python docs/assets/readme/derive.py readme"
    )


def test_data_json_counts_agree_with_each_other() -> None:
    data = _data()
    assert sum(data["tiers"].values()) == data["policies"]
    assert sum(data["claude_code_labels"].values()) == data["policies"]
    assert 0 < data["eval_executed"] <= data["eval_cases"]
    assert len(data["source"]["commit"]) == 40


def test_repo_table_is_repos_json() -> None:
    repos = json.loads((ASSETS / "repos.json").read_text(encoding="utf-8"))
    assert _data()["repos"] == repos, "data.json is behind repos.json; run: python docs/assets/readme/derive.py repos"
    assert len({r["name"] for r in repos}) == len(repos)


def test_every_plugin_client_is_tested_or_untested_exactly_once() -> None:
    tested, untested = _derive().plugin_clients()
    assert tested and untested
    assert not set(tested) & set(untested)


def test_a_deprecated_policy_is_not_counted(tmp_path: Path) -> None:
    def entry(pid: str, status: str) -> dict:
        label = {"claude-code": {"keyword": "block"}}
        return {
            "id": pid,
            "status": status,
            "enforces": "enforced-at-commit",
            "label": label,
            "eval_cases": 3,
            "eval_executed": 2,
        }

    derive = _derive()
    ids = sorted({pid for _, pid in derive.INCIDENTS})
    policies = [entry(pid, "production") for pid in ids] + [entry("retired", derive.DEPRECATED)]
    (tmp_path / "registry.yaml").write_text(json.dumps({"policies": policies}), encoding="utf-8")

    data = derive.derive_catalog(tmp_path, "0" * 40)

    live = len(ids)
    assert data["policies"] == live
    assert data["eval_cases"] == 3 * live
    assert data["eval_executed"] == 2 * live
    assert sum(data["tiers"].values()) == live

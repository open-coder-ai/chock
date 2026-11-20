"""The "Which agents, and how strongly Chock holds in each" picture is derived from the code, never typed."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import struct
import subprocess

import pytest
from readme_figure_support import ASSETS, ROOT

JSON = ASSETS / "agents.json"
HEX40 = re.compile(r"[0-9a-f]{40}")


def _derive():
    spec = importlib.util.spec_from_file_location("agents_data", ASSETS / "agents_data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _committed() -> dict:
    return json.loads(JSON.read_text(encoding="utf-8"))


def test_agents_json_equals_what_the_code_derives_now() -> None:
    committed = _committed()
    assert HEX40.fullmatch(committed["source"]["commit"])
    now = _derive().derive(committed["source"]["commit"])
    assert committed == now, "agents.json is behind the code; run: python docs/assets/readme/derive.py readme"


def test_one_row_per_surface_agent_in_the_documented_order() -> None:
    from chock.compile.surfaces import SURFACE_AGENTS

    rows = _committed()["rows"]
    assert {r["id"] for r in rows} == set(SURFACE_AGENTS) and len(rows) == len(SURFACE_AGENTS)
    order = {"tested live": 0, "untested": 1, "": 2}
    keys = [(order[r["plugin"]], r["name"].lower()) for r in rows]
    assert keys == sorted(keys)


def test_cells_match_surfaces_grades_and_the_readme_summary() -> None:
    from chock.compile.surfaces import SURFACE_AGENTS, Surface

    derive = _derive()
    data = _committed()
    for row in data["rows"]:
        surfaces = SURFACE_AGENTS[row["id"]]
        assert row["ci"] is (Surface.CI_GATE in surfaces) and row["git"] is True and row["rule"] is True
        has_hook = bool({Surface.PRE_TOOL_USE, Surface.AGENT_HOOKS} & surfaces)
        assert (row["hook_grade"] != "none") == has_hook == bool(row["hook"])
        assert row["hook"] == derive.GRADE_WORDS[row["hook_grade"]]
        assert row["matrix_pre_tool"] in derive.GRADE_WORDS
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    counts = data["counts"]
    assert sum(1 for r in data["rows"] if r["plugin"] == "tested live") == counts["plugin_tested"]
    assert f"All {counts['agents']} above get" in readme and f"{counts['own_hook']} also get a native hook" in readme
    assert f"{counts['plugin_tested']} tested, {counts['plugin_untested']} untested" in readme


def test_display_names_are_the_ones_the_readme_table_uses() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    table = readme.split("### Supported agents", 1)[1]
    for name in _derive().NAMES.values():
        assert f"| **{name}** |" in table, name


def test_no_text_is_typed_into_the_layout() -> None:
    layout = (ASSETS / "agents.mjs").read_text(encoding="utf-8")
    for word in ("refuses", "advice", "tested", "fails open", "Which agents"):
        assert word not in layout, word


def _node(script: str) -> object:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [node, "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_no_text_overflows_a_card() -> None:
    script = (
        "import {layout, crowded} from './docs/assets/readme/agents.mjs';"
        "import {readFileSync} from 'node:fs';"
        "const W = JSON.parse(readFileSync('docs/assets/readme/agents.json', 'utf8'));"
        "console.log(JSON.stringify(crowded(layout(W))));"
    )
    assert _node(script) == []


def test_title_is_the_teaching_one_and_chock_is_named_only_in_the_footer() -> None:
    data = _committed()
    assert data["title"] == "Where each coding agent can be stopped"
    text = json.dumps({k: v for k, v in data.items() if k not in ("footer", "source")}).lower()
    assert "chock" not in text and "chock" in data["footer"].lower()
    assert data["footer"].count(data["source"]["commit"][:7]) == 1
    assert list(data["groups"].values()) == ["One plugin, tested live", "One plugin, untested", "Git hook and CI"]


def test_png_exists_is_two_x_wide_and_is_registered_and_no_site_render_exists() -> None:
    png = ASSETS / "v2" / "agents.png"
    assert png.stat().st_size > 10_000
    assert struct.unpack(">II", png.read_bytes()[16:24])[0] == 1760
    assert not (ASSETS / "v2" / "agents-site.png").exists()
    render = (ASSETS / "render.mjs").read_text(encoding="utf-8")
    assert "'v2/agents': AGENTS_PNG" in render and "agents-site" not in render


def test_adapters_page_links_the_picture_and_the_readme_stays_untouched() -> None:
    page = (ROOT / "docs" / "adapters" / "README.md").read_text(encoding="utf-8")
    assert "../assets/readme/v2/agents.png" in page
    assert "agents.png" not in (ROOT / "README.md").read_text(encoding="utf-8")

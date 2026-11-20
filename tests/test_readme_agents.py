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
        assert bool(row["ci"]) == (Surface.CI_GATE in surfaces) and row["git"] and row["rule"]
        has_hook = bool({Surface.PRE_TOOL_USE, Surface.AGENT_HOOKS} & surfaces)
        assert (row["hook_grade"] != "none") == has_hook == bool(row["hook"])
        assert row["hook"] == derive.GRADE_WORDS[row["hook_grade"]]
        assert row["matrix_pre_tool"] in derive.GRADE_WORDS
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    counts = data["counts"]
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


def test_site_palette_render_has_the_same_layout_as_the_default() -> None:
    script = (
        "import {where, DEFAULT_PALETTE, SITE_PALETTE} from './docs/assets/readme/agents.mjs';"
        "import {readFileSync} from 'node:fs';"
        "const W = JSON.parse(readFileSync('docs/assets/readme/agents.json', 'utf8'));"
        "const strip = (h) => h.replace(/#[0-9a-fA-F]{3,8}\\b/g, '#');"
        "const a = where((b) => b, W), b = where((b) => b, W, SITE_PALETTE);"
        "console.log(JSON.stringify({same: strip(a) === strip(b), differs: a !== b,"
        " keys: Object.keys(DEFAULT_PALETTE.fill).join() === Object.keys(SITE_PALETTE.fill).join()}));"
    )
    assert _node(script) == {"same": True, "differs": True, "keys": True}


def test_both_pngs_exist_with_the_same_size_and_are_registered() -> None:
    sizes = []
    for name in ("agents", "agents-site"):
        png = ASSETS / "v2" / f"{name}.png"
        assert png.stat().st_size > 10_000, name
        sizes.append(struct.unpack(">II", png.read_bytes()[16:24]))
    assert sizes[0] == sizes[1]
    render = (ASSETS / "render.mjs").read_text(encoding="utf-8")
    assert "'v2/agents': AGENTS_PNG" in render and "'v2/agents-site': AGENTS_SITE" in render


def test_adapters_page_links_the_picture_and_the_readme_stays_untouched() -> None:
    page = (ROOT / "docs" / "adapters" / "README.md").read_text(encoding="utf-8")
    assert "../assets/readme/v2/agents.png" in page
    assert "agents.png" not in (ROOT / "README.md").read_text(encoding="utf-8")

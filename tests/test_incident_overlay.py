"""The incident overlay draws only on the published harness figure, rings only recorded refusals and keeps the product name in the footer."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess

import pytest
from readme_figure_support import ASSETS, FIGURE, ROOT

SLUG = "claude-settings-secrets"
SPEC = json.loads((ASSETS / "incidents" / f"{SLUG}.json").read_text(encoding="utf-8"))
PNG = ASSETS / "v2" / "incidents" / f"{SLUG}.png"
POINTS = {p["id"] for p in FIGURE["points"]}


def _node(script: str) -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [node, "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_png_exists_and_is_the_size_the_page_renders_at() -> None:
    assert PNG.stat().st_size > 10_000
    width, height = struct.unpack(">II", PNG.read_bytes()[16:24])
    assert width == 1760 and height > 2000


def test_overlay_builds_without_a_crowded_card_and_edges_match_the_layout() -> None:
    script = (
        "import {incident, EDGES} from './docs/assets/readme/incident-overlay.mjs';"
        "import {layout, crowded} from './docs/assets/readme/where-chock-sits.mjs';"
        "import {readFileSync} from 'node:fs';"
        "const r = (p) => JSON.parse(readFileSync(p, 'utf8'));"
        f"const W = r('docs/assets/readme/where-chock-sits.json'), S = r('docs/assets/readme/incidents/{SLUG}.json');"
        "incident((b) => b, W, S);"
        "console.log(JSON.stringify({crowded: crowded(layout(W)), edges: layout(W).segs.length === EDGES.length}));"
    )
    assert json.loads(_node(script)) == {"crowded": [], "edges": True}


def test_every_ring_is_a_real_badge_and_solid_rings_have_a_recorded_refusal() -> None:
    assert {r["point"] for r in SPEC["rings"] + SPEC["dashed"]} <= POINTS
    assert not {r["point"] for r in SPEC["rings"]} & {r["point"] for r in SPEC["dashed"]}
    assert SPEC["rings"] and SPEC["refusals"]
    assert all(r["exit"] == "1" and "Potential secret detected" in r["text"] for r in SPEC["refusals"])


def test_dashed_labels_never_claim_a_catch() -> None:
    for ring in SPEC["dashed"]:
        assert "could" in ring["label"] and "caught" not in ring["label"] and "refuse" not in ring["label"]


def test_the_product_name_is_only_in_the_footer() -> None:
    text = json.dumps({k: v for k, v in SPEC.items() if k not in ("_", "footer", "alt")}).lower()
    assert "chock" not in text and "chock" in SPEC["footer"].lower()

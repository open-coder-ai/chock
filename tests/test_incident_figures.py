"""Incident teardown figures: the PNG exists at the size its layout computes and no shape is crowded."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess

import pytest
from readme_figure_support import ASSETS, ROOT

SLUGS = ["tj-actions"]
SCRIPT = (
    "import {layout, crowded} from './docs/assets/readme/incident.mjs';"
    "import {readFileSync} from 'node:fs';"
    "const D = JSON.parse(readFileSync('docs/assets/readme/incident-%s.json', 'utf8'));"
    "const L = layout(D);"
    "console.log(JSON.stringify({bad: crowded(L), height: L.height}));"
)


def _layout(slug: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [node, "--input-type=module", "-e", SCRIPT % slug], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.parametrize("slug", SLUGS)
def test_no_card_or_label_is_crowded(slug: str) -> None:
    assert _layout(slug)["bad"] == []


@pytest.mark.parametrize("slug", SLUGS)
def test_png_exists_at_the_layout_size(slug: str) -> None:
    png = ASSETS / "v2" / "incidents" / f"{slug}.png"
    assert png.is_file()
    width, height = struct.unpack(">II", png.read_bytes()[16:24])
    assert (width, height) == (1760, 2 * _layout(slug)["height"])


@pytest.mark.parametrize("slug", SLUGS)
def test_chock_is_named_only_in_the_footer(slug: str) -> None:
    data = json.loads((ASSETS / f"incident-{slug}.json").read_text(encoding="utf-8"))
    footer = data.pop("footer")
    assert "Chock" in footer and "chock" not in json.dumps(data).lower()

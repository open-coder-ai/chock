"""The figures drift check runs on a fixed runner image, so a PNG cannot drift without a repo change."""

from __future__ import annotations

from pathlib import Path

import yaml

FIGURES = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "figures.yml"


def test_figures_job_pins_its_runner_image() -> None:
    runs_on = yaml.safe_load(FIGURES.read_text(encoding="utf-8"))["jobs"]["figures"]["runs-on"]
    assert isinstance(runs_on, str), f"figures runs-on must be one image label, got {runs_on!r}"
    assert not runs_on.endswith("-latest"), (
        f"figures runs on {runs_on!r}; *-latest rolls to a new image whose cairo/fonts re-rasterize "
        f"docs/figures/social-card.png. Pin a versioned image (e.g. ubuntu-24.04) and commit its PNG."
    )

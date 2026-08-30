"""Render chock's GitHub social preview card.

Run from this directory:

    pip install cairosvg      # asset tooling only
    python gen_brand_assets.py

Writes social-preview.svg/.png (1280x640, GitHub's social-preview size) beside this file.
The wheel-and-wedge logo is hand-drawn and lives in logo.svg; this script does not touch it.

cairosvg is NOT a dependency of chock. This is design tooling a maintainer runs by hand
when the artwork changes, and its output is committed.

Every list and count on the card is READ FROM THE PACKAGE at render time -- agents from
config.SURFACE_AGENTS, surfaces from the Surface enum, commands from cli.EVERYDAY, the
rest from pyproject.toml. A social preview is a claim surface, and the surest way to keep
one honest is to leave it no independent copy of the truth to drift from. The counts
printed beside each list are len() of that list, and an over-long row raises rather than
running silently out of its panel.
"""

import pathlib
import sys
import tomllib

from brandkit import GOLD, H, W, card, check, write

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


from chock.cli import EVERYDAY  # noqa: E402
from chock.compile.surfaces import INSTALLED_SURFACES, Surface  # noqa: E402
from chock.config import SURFACE_AGENTS  # noqa: E402


def chock_mark(cx, cy, s):
    """The wheel, and the chock holding it. A small-size echo of logo.svg, without the
    spokes -- at header scale they turn to mud."""
    r, sw = s * 0.20, s * 0.055
    gy = cy + s * 0.26
    return "\n  ".join(
        [
            f'<circle cx="{cx:.1f}" cy="{cy - s * 0.06:.1f}" r="{r:.1f}" fill="none" '
            f'stroke="{GOLD}" stroke-width="{sw:.2f}" stroke-opacity="0.95"/>',
            f'<circle cx="{cx:.1f}" cy="{cy - s * 0.06:.1f}" r="{r * 0.30:.1f}" fill="{GOLD}" fill-opacity="0.55"/>',
            f'<path d="M {cx - s * 0.34:.1f} {gy:.1f} L {cx - s * 0.06:.1f} {gy:.1f} '
            f'L {cx - s * 0.30:.1f} {gy - s * 0.20:.1f} Z" fill="{GOLD}"/>',
            f'<line x1="{cx - s * 0.36:.1f}" y1="{gy:.1f}" x2="{cx + s * 0.36:.1f}" y2="{gy:.1f}" '
            f'stroke="{GOLD}" stroke-width="{sw:.2f}" stroke-opacity="0.55" stroke-linecap="round"/>',
        ]
    )


PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
VERSION = PROJECT["version"]
N_DEPS = len(PROJECT["dependencies"])
PY_ROWS = sorted(
    (c.rsplit(" ", 1)[-1] for c in PROJECT["classifiers"] if "Python :: 3." in c),
    key=lambda v: int(v.split(".")[1]),
)
PY_RANGE = f"PYTHON {PY_ROWS[0]}–{PY_ROWS[-1]}" if PY_ROWS else "PYTHON " + PROJECT["requires-python"]

# claude first because it is the surface most readers arrive from; the rest alphabetical,
# so the order is deterministic rather than set-iteration order.
AGENTS = sorted(SURFACE_AGENTS, key=lambda a: (a != "claude", a))
SURFACES = [s.value for s in Surface]
INSTALLED = sorted(s.value for s in INSTALLED_SURFACES)
COMMANDS = list(EVERYDAY)

ALT = (
    "chock — governance-as-code for AI coding agents: write a rule once and every agent obeys "
    "it. A policy compiles to whatever control each agent actually supports. "
    f"{len(AGENTS)} agents ({', '.join(AGENTS)}); {len(SURFACES)} enforcement surfaces "
    f"({', '.join(SURFACES)}), of which {len(INSTALLED)} are installed by chock sync "
    f"({', '.join(INSTALLED)}); {len(COMMANDS)} everyday commands ({', '.join(COMMANDS)}). "
    f"{PY_RANGE.title()}, Apache-2.0, on PyPI as chock, version {VERSION}."
)

CARD = card(
    name="chock",
    repo="open-coder-ai/chock",
    pill=f"v{VERSION} · APACHE-2.0",
    badge_art=chock_mark(64, 58, 38),
    eyebrow="— GOVERNANCE AS CODE",
    head1="Write the rule once.",
    head2="Every agent obeys it.",
    blurb=[
        "A policy compiles to whatever control each agent",
        "actually supports — git hooks, CI gates, native",
        "pre-execution hooks, AGENTS.md. Not prose to ignore.",
    ],
    api_label="THE EVERYDAY LOOP",
    api_lines=["chock add protect-main-branch", "chock sync"],
    motto="COVERAGE IS GRADED PER AGENT, NEVER ROUNDED UP",
    columns=[
        [("AGENTS", AGENTS)],
        [("SURFACES", SURFACES)],
        [("COMMANDS", COMMANDS)],
    ],
    stats=[
        (str(len(AGENTS)), "AGENTS"),
        (str(len(SURFACES)), "SURFACES"),
        (str(len(COMMANDS)), "COMMANDS"),
        (str(N_DEPS), "DEPENDENCIES"),
    ],
    right_foot=f"{PY_RANGE} · APACHE-2.0 · PYPI: chock",
    alt=ALT,
)

if __name__ == "__main__":
    if "--check" in sys.argv:
        problems = check(CARD, "social-preview")
        if problems:
            print("\n".join(problems))
            print(
                "\nThe card is derived from the repository, so this means the repository "
                "changed.\nRegenerate it:  python docs/assets/gen_brand_assets.py"
            )
            raise SystemExit(1)
        print("social-preview.svg is current")
        raise SystemExit(0)
    write(CARD, "social-preview", W, H)
    print(f"rendered: {len(AGENTS)} agents, {len(SURFACES)} surfaces, {len(COMMANDS)} commands, v{VERSION}")

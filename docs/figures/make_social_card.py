"""chock's GitHub social-preview card: name, one line, one number -- nothing else.

Light theme only (GitHub's social preview has no dark variant). The number is
`len(SURFACE_AGENTS)`, the same count `make_surfaces.py` puts on its "one policy" fan-out, so
the two figures cannot drift apart on what chock claims to support.

chock already ships a separate, more elaborate social-preview asset
(docs/assets/social-preview.svg, built by docs/assets/gen_brand_assets.py) that a maintainer
uploads as the repository's actual GitHub social image. This card is the block-2 programme's
own minimal one, in the shared palette idiom; see the launch report for why both exist rather
than one replacing the other.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import palette as p

from chock.compile.surfaces import SURFACE_AGENTS

W, H = 1280, 640


def render(t):
    n_agents = len(SURFACE_AGENTS)
    svg = p.open_svg(
        W,
        H,
        t,
        "chock",
        f"chock: one policy, compiled to every supported coding agent. {n_agents} agents supported.",
    )
    svg += p.text(80, 260, "chock", t["text"], 96, p.MONO, "700")
    svg += p.text(80, 330, "one policy, compiled to every coding agent", t["secondary"], 28)
    svg += p.text(80, 470, str(n_agents), t["enforcement"][1], 120, p.MONO, "700")
    svg += p.text(266, 470, "agents supported", t["secondary"], 28)
    return svg + p.close_svg()


if __name__ == "__main__":
    svg = render(p.theme("light"))
    with open("social-card.svg", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(svg)
    print("wrote social-card.svg")
    try:
        import cairosvg
    except ImportError:
        print("cairosvg not installed -- social-card.png left untouched")
    else:
        cairosvg.svg2png(url="social-card.svg", write_to="social-card.png", output_width=W, output_height=H)
        print("wrote social-card.png")

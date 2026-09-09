"""The open-coder-ai family: what each repository is, and what feeds what.

Carried byte-identically by four repositories; see palette.py on why every
statement stays on one line under 88 characters.
"""

import palette as p

W, H = 800, 420
NAME, ROLE = 13, 11
WIDE, NARROW, ARM = 74, 34, 22

# Split into fragments joined with a space: a magic trailing comma keeps each list
# exploded, so `ruff format` leaves this alone at 88, 100 and 120 alike.
ROLES = {
    "agentseam": [
        "the primitives — one handler API and a verified capability",
        "matrix across 16 agents",
    ],
    "chock": [
        "the compiler — one policy into git hooks, CI gates and",
        "native pre-tool hooks",
    ],
    "chock-catalog": [
        "the policies — 39, each labelled enforced or advisory,",
        "with replayed evals",
    ],
    "context-report": [
        "the evidence — a signed report of whether an agent",
        "artifact actually works",
    ],
    "chock-threat-intel": ["the threat ledger the catalog's policies answer to"],
    "plugins": ["the catalog, packaged for each agent's plugin format (generated)"],
}


def role(key):
    """One repository's one-line description, reassembled from its fragments."""
    return " ".join(ROLES[key])


def _block(rect, name, role, t, filled, chars):
    """A repository: monospace identifier, wrapped role beneath it."""
    x, y, w, h = rect
    accent = t["enforcement"][1]
    fill = accent if filled else t["surface"]
    out = p.box(x, y, w, h, fill, None if filled else accent)
    label = t["surface"] if filled else t["text"]
    body = t["surface"] if filled else t["secondary"]
    out += p.text(x + 12, y + 22, name, label, NAME, p.MONO, "600")
    for i, line in enumerate(p.wrap(role, chars)):
        out += p.text(x + 12, y + 40 + i * 15, line, body, ROLE)
    return out


DESC = (
    "A layered diagram. agentseam is the foundation across the bottom; chock sits "
    "on it; chock-catalog feeds chock and generates the four plugin repositories; "
    "chock-threat-intel feeds the catalog; context-report runs as a verification "
    "arm beside all of them."
)


def render(t, name):
    """One theme's copy of the family diagram."""
    a = t["enforcement"][1]
    svg = p.open_svg(W, H, t, "The open-coder-ai family", DESC)

    intel = role("chock-threat-intel")
    svg += _block((24, 24, 262, 72), "chock-threat-intel", intel, t, False, NARROW)

    svg += p.box(314, 24, 262, 72, t["surface"], t["neutral"])
    svg += p.text(326, 44, "plugin repositories", t["text"], NAME, p.MONO, "600")
    for i, line in enumerate(p.wrap(role("plugins"), NARROW)):
        svg += p.text(326, 62 + i * 15, line, t["secondary"], ROLE)

    svg += p.arrow(155, 96, 155, 122, a)
    svg += p.arrow(445, 122, 445, 96, a)

    cat = role("chock-catalog")
    svg += _block((24, 124, 552, 74), "chock-catalog", cat, t, True, WIDE)
    svg += p.arrow(300, 198, 300, 224, a)
    svg += _block((24, 226, 552, 74), "chock", role("chock"), t, True, WIDE)
    svg += p.arrow(300, 328, 300, 302, a)
    svg += _block((24, 330, 552, 74), "agentseam", role("agentseam"), t, True, WIDE)

    svg += p.box(596, 24, 180, 380, t["surface"], a)
    svg += p.text(608, 46, "context-report", t["text"], NAME, p.MONO, "600")
    for i, line in enumerate(p.wrap(role("context-report"), ARM)):
        svg += p.text(608, 68 + i * 15, line, t["secondary"], ROLE)
    svg += p.text(608, 390, "measures all four", t["secondary"], ROLE)
    for y in (140, 242, 346):
        svg += p.arrow(592, y, 580, y, a)

    return svg + p.close_svg()


if __name__ == "__main__":
    for path in p.write_pair("family", render):
        print("wrote", path)

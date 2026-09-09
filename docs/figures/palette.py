"""The one visual language every open-coder-ai figure is drawn in.

Four repositories carry this file byte-identically while configuring `ruff format` at
three different line lengths (88, 100 and 120), so no formatted output could satisfy all
of them. Every statement here therefore fits on a single line under 88 characters and
nothing is split across lines: a formatter at any width finds nothing to join or wrap.
Keep it that way when editing.
"""

# Enforcement is ordinal: advisory < in-agent < enforced. Never reorder these.
ENFORCEMENT = {
    "light": ["#86b6ef", "#2a78d6", "#104281"],
    "dark": ["#9ec5f4", "#3987e5", "#184f95"],
}

# agentseam grades five levels; the ramp is the same hue walked further.
LEVELS = {
    "light": ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"],
    "dark": ["#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"],
}

# Absence is not a low score, so it is never a ramp colour.
NEUTRAL = {"light": "#d8d7d2", "dark": "#383835"}

SURFACE = {"light": "#fcfcfb", "dark": "#1a1a19"}
TEXT = {"light": "#0b0b0b", "dark": "#ffffff"}
TEXT_SECONDARY = {"light": "#52514e", "dark": "#c3c2b7"}

STROKE_WIDTH = 2
CORNER = 4
GAP = 2  # surface showing between adjacent fills
GRID_OPACITY = 0.3

SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"

THEMES = ("light", "dark")

_XML = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;"))


def theme(name):
    """Every colour of one theme, resolved."""
    return {
        "enforcement": ENFORCEMENT[name],
        "levels": LEVELS[name],
        "neutral": NEUTRAL[name],
        "surface": SURFACE[name],
        "text": TEXT[name],
        "secondary": TEXT_SECONDARY[name],
    }


def esc(s):
    """XML-escape a label."""
    out = str(s)
    for old, new in _XML:
        out = out.replace(old, new)
    return out


def open_svg(width, height, t, title, desc):
    """An accessible root element: the title and description are the alt text."""
    ns = 'xmlns="http://www.w3.org/2000/svg"'
    size = f'width="{width:d}" height="{height:d}"'
    view = f'viewBox="0 0 {width:d} {height:d}"'
    root = f'<svg {ns} {size} {view} role="img" aria-labelledby="t d">\n'
    alt = f'  <title id="t">{esc(title)}</title>\n'
    alt += f'  <desc id="d">{esc(desc)}</desc>\n'
    return root + alt + f'  <rect {size} fill="{t["surface"]}"/>\n'


def close_svg():
    return "</svg>\n"


def box(x, y, w, h, fill, stroke=None, rx=CORNER):
    """A rounded rectangle, filled and optionally outlined."""
    edge = f' stroke="{stroke}" stroke-width="{STROKE_WIDTH:d}"' if stroke else ""
    geom = f'x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}"'
    return f'  <rect {geom} rx="{rx:d}" fill="{fill}"{edge}/>\n'


def text(x, y, s, fill, size=13, family=SANS, weight="400", anchor="start"):
    """One line of type, anchored at (x, y)."""
    font = f'font-family="{family}" font-size="{size:g}" font-weight="{weight}"'
    place = f'x="{x:g}" y="{y:g}"'
    paint = f'fill="{fill}" text-anchor="{anchor}"'
    return f"  <text {place} {font} {paint}>{esc(s)}</text>\n"


def arrow(x1, y1, x2, y2, colour, head=6):
    """A straight connector with a solid head, drawn direction-aware."""
    ends = f'x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}"'
    paint = f'stroke="{colour}" stroke-width="{STROKE_WIDTH:d}"'
    line = f'  <line {ends} {paint} stroke-linecap="round"/>\n'
    if x1 == x2:  # vertical: the head's base sits back along the travel
        base = y2 - head if y2 > y1 else y2 + head
        wings = ((x2 - head, base), (x2 + head, base))
    else:
        base = x2 - head if x2 > x1 else x2 + head
        wings = ((base, y2 - head), (base, y2 + head))
    corners = ((x2, y2), *wings)
    pts = " ".join(f"{px:g},{py:g}" for px, py in corners)
    return line + f'  <polygon points="{pts}" fill="{colour}"/>\n'


def write_pair(stem, render):
    """`render(theme_colours, theme_name) -> svg string`, once per theme."""
    written = []
    for name in THEMES:
        path = f"{stem}-{name}.svg"
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render(theme(name), name))
        written.append(path)
    return written


def wrap(s, width):
    """Greedy wrap to `width` characters, so a label fits without a font metric."""
    words, lines, line = s.split(), [], ""
    for w in words:
        candidate = (line + " " + w).strip()
        if len(candidate) > width and line:
            lines.append(line)
            line = w
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines

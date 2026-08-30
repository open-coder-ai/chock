"""Shared drawing primitives for this repository's brand assets.

Split out of gen_brand_assets.py to stay inside the review budget the repo standards
enforce: this file is the drawing language (palette, text, panels, the card layout), and
gen_brand_assets.py is what this particular repository has to say. Two activities, two
files.

Nothing here knows anything about chock: it takes lists and labels and returns SVG.
The assertions are the point -- a row too long for its panel, or a left column that would
run into the footer rule, raises rather than rendering something subtly broken.
"""

import pathlib
import re

import cairosvg

NAVY = "#0D1626"
PANEL = "#111E33"
GOLD = "#D9B45C"
DIM = "#8A7340"
COOL = "#9FB0C4"
FAINT = "#5A6B80"
WHITE = "#E8EEF6"
FONT = "Geist Mono"
W, H = 1280, 640
LOGO_SIZE = 512
MAX_ROWS = 12
ROW_SIZE = 12.5


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, size, fill, body, weight=None, tracking=None, anchor=None):
    attrs = [f'x="{x}"', f'y="{y}"', f'font-family="{FONT}"', f'font-size="{size}"']
    if weight:
        attrs.append(f'font-weight="{weight}"')
    if tracking is not None:
        attrs.append(f'letter-spacing="{tracking}"')
    if anchor:
        attrs.append(f'text-anchor="{anchor}"')
    attrs.append(f'fill="{fill}"')
    return "<text " + " ".join(attrs) + f">{esc(body)}</text>"


def fits(w, size=ROW_SIZE, pad=17, bullet=13):
    """How many Geist Mono characters fit one row of a panel this wide (~0.6em advance)."""
    return int((w - pad * 2 - bullet) / (size * 0.6))


def diamond(cx, cy, r, fill=GOLD):
    return (
        f'<rect x="{cx - r:.2f}" y="{cy - r:.2f}" width="{r * 2:.2f}" height="{r * 2:.2f}" '
        f'transform="rotate(45 {cx:.2f} {cy:.2f})" fill="{fill}"/>'
    )


def badge(cx, cy, s, art):
    """A mark on the header chip: PANEL ground, for use on the NAVY card."""
    return (
        f'<rect x="{cx - s / 2:.1f}" y="{cy - s / 2:.1f}" width="{s}" height="{s}" '
        f'rx="{s * 0.22:.1f}" fill="{PANEL}"/>\n  ' + art
    )


def logo_svg(art, alt, size=LOGO_SIZE):
    """A mark as a standalone square logo: NAVY ground."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" role="img"\n'
        f'     aria-label="{esc(alt)}">\n'
        f'  <rect width="{size}" height="{size}" rx="{size * 0.203:.0f}" fill="{NAVY}"/>\n  ' + art + "\n</svg>"
    )


def column(x, y, w, h, groups):
    """A bordered panel of labelled lists. Counts are len() of the list beside them."""
    parts = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{PANEL}" '
        f'stroke="{GOLD}" stroke-opacity="0.16" stroke-width="1"/>'
    ]
    pad = 17
    cy = y + 29
    limit = fits(w)
    for index, (label, rows) in enumerate(groups):
        total = len(rows)
        shown = rows[: MAX_ROWS - 1] if total > MAX_ROWS else rows
        if index:
            cy += 20
        parts.append(f'<circle cx="{x + pad + 3}" cy="{cy - 4}" r="2.6" fill="{GOLD}" fill-opacity="0.9"/>')
        parts.append(text(x + pad + 13, cy, 11, GOLD, label, weight=700, tracking=2.3))
        parts.append(text(x + w - pad, cy, 14, GOLD, str(total), weight=700, anchor="end"))
        cy += 11
        parts.append(
            f'<line x1="{x + pad}" y1="{cy}" x2="{x + w - pad}" y2="{cy}" stroke="{GOLD}" '
            f'stroke-opacity="0.14" stroke-width="1" stroke-dasharray="2 3"/>'
        )
        cy += 21
        for i, row in enumerate(shown):
            # Nothing clips an over-long row: it runs silently out of the panel and into
            # the next column. Two real identifier lists did exactly that. Assert instead.
            assert len(row) <= limit, f"row {row!r} ({len(row)}) overflows a {w}px column (max {limit})"
            parts.append(f'<circle cx="{x + pad + 3}" cy="{cy - 4}" r="1.7" fill="{COOL}" fill-opacity="0.5"/>')
            parts.append(text(x + pad + 13, cy, ROW_SIZE, WHITE if i == 0 else COOL, row))
            cy += 26
        if total > len(shown):
            parts.append(text(x + pad + 13, cy - 4, 11.5, FAINT, f"+ {total - len(shown)} more"))
            cy += 22
    return "\n  ".join(parts)


def card(
    *,
    name,
    repo,
    pill,
    eyebrow,
    head1,
    head2,
    blurb,
    api_label,
    api_lines,
    motto,
    columns,
    stats,
    right_foot,
    badge_art,
    alt,
    extras=None,
):
    n = len(columns)
    assert n in (2, 3), "the card takes two or three columns"
    span, gap = 1232 - 506, 18
    cw = int((span - gap * (n - 1)) / n)
    cx = [506 + i * (cw + gap) for i in range(n)]
    cy, ch = 118, 378
    body = [
        f'<rect width="{W}" height="{H}" fill="{NAVY}"/>',
        badge(64, 58, 38, badge_art),
        text(90, 64, 19, GOLD, name, weight=700, tracking=-0.4),
        text(int(90 + len(name) * 12.2), 64, 12, FAINT, repo),
        f'<rect x="1042" y="44" width="190" height="27" rx="13" fill="{PANEL}" stroke="{GOLD}" stroke-opacity="0.22"/>',
        f'<circle cx="1062" cy="57.5" r="3.2" fill="{GOLD}"/>',
        text(1074, 62, 11, GOLD, pill, tracking=0.2),
        f'<line x1="48" y1="92" x2="1232" y2="92" stroke="{GOLD}" stroke-opacity="0.13" stroke-width="1"/>',
        text(48, 140, 10.5, DIM, eyebrow, tracking=3.4),
        text(48, 190, 33, WHITE, head1, weight=700, tracking=-1.2),
        text(48, 230, 33, GOLD, head2, weight=700, tracking=-1.2),
    ]
    yy = 276
    for line in blurb:
        body.append(text(48, yy, 13, COOL, line))
        yy += 22
    body.append(text(48, 372, 10.5, DIM, api_label, tracking=3.4))
    body.append(
        f'<rect x="48" y="386" width="410" height="{26 + 24 * len(api_lines)}" rx="9" '
        f'fill="{PANEL}" stroke="{GOLD}" stroke-opacity="0.16"/>'
    )
    yy = 412
    for i, line in enumerate(api_lines):
        body.append(text(66, yy, 12.5, GOLD if i == len(api_lines) - 1 else COOL, line))
        yy += 24
    if extras:
        body.append(
            f'<line x1="48" y1="472" x2="458" y2="472" stroke="{GOLD}" stroke-opacity="0.10" stroke-width="1"/>'
        )
    for i, (label, value) in enumerate(extras or []):
        body.append(text(48, 484 + i * 22, 11, DIM, label, tracking=1.9))
        body.append(text(458, 484 + i * 22, 11.5, COOL, value, anchor="end"))
    motto_y = 498 if not extras else 484 + len(extras) * 22
    assert motto_y <= 550, f"the left column overflows the footer rule (motto at y={motto_y})"
    body.append(text(48, motto_y, 10.5, DIM, motto, tracking=1.55))
    for i, group in enumerate(columns):
        body.append(column(cx[i], cy, cw, ch, group))
    body.append(f'<line x1="48" y1="560" x2="1232" y2="560" stroke="{GOLD}" stroke-opacity="0.13" stroke-width="1"/>')
    sx = 48
    for number, label in stats:
        body.append(text(int(sx), 590, 15, GOLD, number, weight=700))
        sx += len(number) * 12 + 4
        body.append(text(int(sx), 590, 10.5, FAINT, label, tracking=1.6))
        sx += len(label) * 8.1 + 26
    assert sx < 900, "the footer stats run into the right-hand footer line"
    body.append(text(1232, 590, 10.5, FAINT, right_foot, tracking=1.4, anchor="end"))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}"\n'
        f'     role="img" aria-label="{esc(alt)}">\n  ' + "\n  ".join(body) + "\n</svg>"
    )


def write(svg, stem, w, h, png_stem=None):
    with open(f"{stem}.svg", "w", encoding="utf-8") as fh:
        fh.write(svg)
    cairosvg.svg2png(bytestring=svg.encode(), write_to=f"{png_stem or stem}.png", output_width=w, output_height=h)


def check(svg, stem):
    """Compare a freshly derived card against the committed one; report what drifted.

    The committed image is a snapshot of facts that live in the repository, so adding a
    policy, an agent or an event silently invalidates it. Nothing here is hand-typed --
    every count is len() of a list read at render time -- but a stale PNG is wrong all the
    same. CI runs this so the artifact cannot drift unnoticed, the same discipline the
    compiled artifacts are already held to.

    The comparison is on the SVG, never the PNG: the SVG is plain text derived only from
    repository data, so it is byte-identical on any machine, while a PNG depends on the
    font being installed on the renderer. Any drift in the facts reaches the SVG first.
    """
    path = pathlib.Path(f"{stem}.svg")
    if not path.exists():
        return [f"{path} is missing"]
    committed = path.read_text(encoding="utf-8")
    if committed == svg:
        return []
    fresh_rows = re.findall(r">([^<>]+)</text>", svg)
    old_rows = re.findall(r">([^<>]+)</text>", committed)
    added = [r for r in fresh_rows if r not in old_rows]
    removed = [r for r in old_rows if r not in fresh_rows]
    detail = []
    if added:
        detail.append("  now present: " + ", ".join(added[:8]) + (" …" if len(added) > 8 else ""))
    if removed:
        detail.append("  no longer:   " + ", ".join(removed[:8]) + (" …" if len(removed) > 8 else ""))
    return [f"{path} is out of date"] + detail

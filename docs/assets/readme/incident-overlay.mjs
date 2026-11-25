// Incident overlay: the published harness figure (where-chock-sits.mjs, unchanged) with one incident drawn on it. The spec JSON names the path, the numbered steps, the ringed catch points and the refusal text; layout and colours come from the figure.
import { layout, where, DEFAULT_PALETTE } from './where-chock-sits.mjs';

// The order layout() pushes its arrows in; a test asserts the count so a layout change cannot shift the names silently.
export const EDGES = ['you-prompt', 'prompt-loop', 'session-loop', 'context-loop', 'loop-model', 'loop-gate', 'gate-loop', 'gate-tools', 'tools-loop', 'tools-external', 'loop-subagents', 'tools-commit', 'commit-push', 'push-ci', 'ci-main'];
const RED = '#DC2626';
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
const abs = (x, y, w, h, css, inner = '') => `<div style="position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;${css}">${inner}</div>`;

const corners = (d) => [...d.matchAll(/([MHV])(-?[\d.]+)(?: (-?[\d.]+))?/g)].reduce((pts, m) => {
  const [x, y] = pts.length ? pts[pts.length - 1] : [0, 0];
  pts.push(m[1] === 'M' ? [+m[2], +m[3]] : m[1] === 'H' ? [+m[2], y] : [x, +m[2]]);
  return pts;
}, []);
// A point a third of the way along the segment's longest straight run, where a numbered mark fits beside the arrow label.
const markAt = (d) => {
  const p = corners(d), runs = p.slice(1).map((q, i) => [p[i], q]);
  const [a, b] = runs.reduce((best, r) => (Math.hypot(r[1][0] - r[0][0], r[1][1] - r[0][1]) > Math.hypot(best[1][0] - best[0][0], best[1][1] - best[0][1]) ? r : best));
  return [a[0] + (b[0] - a[0]) * 0.3, a[1] + (b[1] - a[1]) * 0.3];
};

export const checkSpec = (L, spec) => {
  if (L.segs.length !== EDGES.length) throw new Error(`layout has ${L.segs.length} arrows, EDGES names ${EDGES.length}`);
  const unknown = [...spec.path.edges, ...spec.steps.map((s) => s.edge)].filter((e) => !EDGES.includes(e));
  if (unknown.length) throw new Error(`unknown edge ${unknown}`);
  const ids = new Set(L.badges.map((b) => b.p.id)), cards = new Set(Object.keys(L.cards));
  [...spec.rings, ...spec.dashed, ...(spec.backstop || [])].filter((r) => !ids.has(r.point)).forEach((r) => { throw new Error(`no badge ${r.point}`); });
  spec.path.cards.filter((c) => !cards.has(c)).forEach((c) => { throw new Error(`no card ${c}`); });
};

export const incident = (page, W, spec, palette = DEFAULT_PALETTE) => {
  const base = JSON.parse(JSON.stringify(W));
  base.harness.title = spec.title;
  if (spec.legend) base.harness.key = { ...base.harness.key, ...spec.legend };
  const backstop = spec.backstop || [];
  const L = layout(base);
  checkSpec(L, spec);
  const { paper: PAPER, ink: INK, soft: SOFT, line: LINE } = palette;
  const edge = (e) => L.segs[EDGES.indexOf(e)];
  const dim = Object.values(L.cards).filter((c) => !spec.path.cards.includes(c.id)).map((c) => abs(c.x, c.y, c.w, c.h, `background:${PAPER};opacity:.62;border-radius:12px`)).join('');
  const marker = `<marker id="r" markerUnits="userSpaceOnUse" markerWidth="14" markerHeight="14" refX="11" refY="7" orient="auto"><path d="M2 2 L12 7 L2 12" fill="none" stroke="${RED}" stroke-width="2.4"/></marker>`;
  const lines = spec.path.edges.map((e) => `<path d="${edge(e).d}" fill="none" stroke="${RED}" stroke-width="3" stroke-linejoin="round" marker-end="url(#r)"/>`).join('');
  const disc = (x, y, text, size = 20) => abs(x - size / 2, y - size / 2, size, size, `border-radius:50%;background:${RED};color:#fff;font-size:12px;font-weight:700;line-height:${size}px;text-align:center`, esc(text));
  const steps = spec.steps.map((s, i) => { const [x, y] = markAt(edge(s.edge).d); return disc(x, y, i + 1); }).join('');
  const ringed = (r, i, kind) => { const b = L.badges.find((q) => q.p.id === r.point), g = 3, c = kind === 'backstop' ? SOFT : RED; return abs(b.x - g, b.y - g, b.w + 2 * g, b.h + 2 * g, `box-sizing:border-box;border:3px ${{ solid: 'solid', dashed: 'dashed', backstop: 'dotted' }[kind]} ${c};border-radius:999px`) + abs(b.x + b.w + g - 9, b.y - g - 9, 18, 18, `border-radius:50%;background:${c};color:#fff;font-size:12px;font-weight:700;line-height:18px;text-align:center`, String.fromCharCode(65 + i)); };
  const nR = spec.rings.length, nD = spec.dashed.length;
  const rings = spec.rings.map((r, i) => ringed(r, i, 'solid')).join('') + spec.dashed.map((r, i) => ringed(r, nR + i, 'dashed')).join('') + backstop.map((r, i) => ringed(r, nR + nD + i, 'backstop')).join('');
  const cropH = 78 + L.Ht + 20 + 56;
  const frame = where((body) => body, base, palette);
  const overlay = `<div style="position:absolute;left:20px;top:78px;width:840px;height:${L.Ht}px">${dim}<svg width="840" height="${L.Ht}" style="position:absolute;left:0;top:0" xmlns="http://www.w3.org/2000/svg"><defs>${marker}</defs>${lines}</svg>${steps}${rings}</div>`;
  const row = (mark, text, round, bg = RED) => `<div style="display:flex;gap:10px;align-items:flex-start;margin-top:8px"><span style="flex:none;width:20px;height:20px;line-height:20px;text-align:center;font-size:12px;font-weight:700;color:#fff;background:${bg};border-radius:${round ? '50%' : '4px'}">${mark}</span><span style="font-size:14px;line-height:20px;color:${INK}">${esc(text)}</span></div>`;
  const key = spec.steps.map((s, i) => row(i + 1, s.text, true)).join('') + spec.rings.map((r, i) => row(String.fromCharCode(65 + i), r.label, false)).join('') + spec.dashed.map((r, i) => row(String.fromCharCode(65 + nR + i), r.label, false)).join('') + backstop.map((r, i) => row(String.fromCharCode(65 + nR + nD + i), r.label, false, SOFT)).join('') + (spec.dashed.length ? `<div style="margin-top:10px;font-size:13px;color:${SOFT}">solid ring: a check the proof ran and recorded. dashed ring: a place a rule can be added.</div>` : '');
  const quotes = (spec.quotes || []).map((q) => `<div style="margin-top:10px"><div style="font-size:15px;line-height:22px;color:${INK}">\u201C${esc(q.text)}\u201D</div>${q.note ? `<div style="margin-top:4px;font-size:13px;font-weight:700;color:${RED}">${esc(q.note)}</div>` : ''}</div>`).join('');
  const refusals = quotes ? quotes : spec.refusals.length
    ? spec.refusals.map((r) => `<div style="margin-top:10px"><div style="font-size:13px;font-weight:700;color:${SOFT}">${esc(r.sample)}: exit ${esc(r.exit)}</div><pre class="mono" style="margin:4px 0 0;white-space:pre-wrap;font-size:13px;line-height:1.5;color:${INK}">${esc(r.text)}</pre></div>`).join('')
    : `<div class="mono" style="margin-top:10px;font-size:13px;color:${SOFT}">no proof recorded yet</div>`;
  return page(`<div id="incident" style="width:880px;background:${PAPER};color:${INK};position:relative">
<div style="position:relative;width:880px;height:${cropH}px;overflow:hidden">${frame}${overlay}</div>
<div style="padding:0 40px 20px"><div style="font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:${SOFT}">${esc(spec.path.title)}</div>${key}
<div style="margin-top:16px;padding:12px 16px;border:1.5px solid ${LINE};border-radius:12px;background:${palette.chip}"><div style="font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:${SOFT}">${esc(spec.refusal_title)}</div>${refusals}</div>
<div style="margin-top:16px;${spec.footer_accent ? `font-size:20px;line-height:1.35;font-weight:700;color:${palette.accent}` : `font-size:16px;color:${SOFT}`}">${esc(spec.footer)}</div></div></div>`);
};

// A 4:5 version for a social feed (1080x1350): title, quotes, only the cards on the path with their rings, one line per ring, footer. Reads spec.compact {cards, labels, note}; the full picture is unchanged.
export const compact = (page, W, spec, palette = DEFAULT_PALETTE) => {
  const { paper: PAPER, ink: INK, soft: SOFT, line: LINE, chip: CHIP, fill: FILL, accent: ACCENT, grey: GREY } = palette, C = spec.compact;
  const kinds = [...spec.rings.map((r) => [r, 'solid']), ...spec.dashed.map((r) => [r, 'dashed']), ...(spec.backstop || []).map((r) => [r, 'dotted'])];
  const named = [...W.harness.cards, ...W.harness.repo_cards];
  const CW = 168, GAP = 36, CH = 220, tone = (k) => (k === 'dotted' ? SOFT : RED);
  const cards = C.cards.map((id, i) => {
    const c = named.find((q) => q.id === id), p = W.points.find((q) => q.on === id && kinds.some(([r]) => r.point === q.id)), k = p && kinds.findIndex(([r]) => r.point === p.id);
    const badge = p ? `<div style="position:absolute;left:8px;right:8px;bottom:16px;height:34px;box-sizing:border-box;display:flex;align-items:center;gap:8px;padding:0 10px;border-radius:999px;background:${CHIP};border:3px ${{ solid: 'solid', dashed: 'dashed', dotted: 'dotted' }[kinds[k][1]]} ${tone(kinds[k][1])};font-size:18px;font-weight:600;color:${p.acts ? ACCENT : GREY}"><span style="flex:none;width:12px;height:12px;transform:rotate(45deg);box-sizing:border-box;border:2px solid ${p.acts ? ACCENT : GREY};background:${p.acts ? ACCENT : PAPER}"></span>${esc(p.label)}<span style="position:absolute;right:-10px;top:-20px;width:28px;height:28px;border-radius:50%;background:${tone(kinds[k][1])};color:#fff;font-size:17px;font-weight:700;line-height:28px;text-align:center">${String.fromCharCode(65 + k)}</span></div>` : '';
    const arrow = i ? `<svg width="${GAP}" height="20" style="position:absolute;left:${-GAP}px;top:${CH / 2 - 10}px"><path d="M2 10 H${GAP - 4}" stroke="${RED}" stroke-width="4"/><path d="M${GAP - 14} 3 L${GAP - 3} 10 L${GAP - 14} 17" fill="none" stroke="${RED}" stroke-width="4"/></svg>` : '';
    return `<div style="position:relative;flex:none;width:${CW}px;height:${CH}px">${arrow}<div style="position:absolute;inset:0;box-sizing:border-box;background:${FILL[id]};border:2px solid ${LINE};border-radius:14px;padding:14px 12px"><div style="font-size:23px;font-weight:700;line-height:27px;color:${INK}">${esc(c.name)}</div><div style="font-size:19px;line-height:24px;color:${SOFT};margin-top:6px">${esc(c.line)}</div></div>${badge}</div>`;
  }).join('');
  const rows = kinds.map(([r, k], i) => `<div style="display:flex;gap:16px;align-items:center;margin-top:${i ? 14 : 0}px"><span style="flex:none;width:34px;height:34px;line-height:34px;text-align:center;font-size:20px;font-weight:700;color:#fff;background:${tone(k)};border-radius:50%">${String.fromCharCode(65 + i)}</span><span style="font-size:28px;line-height:34px;color:${INK}">${esc(C.labels[i])}</span></div>`).join('');
  const quotes = spec.quotes.map((q, i) => `<div style="margin-top:14px;font-size:27px;line-height:36px;color:${INK}">“${esc(q.text)}”${i === spec.quotes.length - 1 ? `<div style="margin-top:8px;font-size:24px;font-weight:700;color:${RED}">${esc(C.note)}</div>` : ''}</div>`).join('');
  return page(`<div id="incident" style="width:1080px;height:1350px;box-sizing:border-box;padding:56px 48px 52px;background:${PAPER};color:${INK};display:flex;flex-direction:column;justify-content:space-between">
<div style="font-size:42px;line-height:1.2;font-weight:600">${esc(spec.title)}</div>
<div style="padding:20px 26px 24px;border:2px solid ${LINE};border-radius:16px;background:${CHIP}"><div style="font-size:16px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:${SOFT}">${esc(spec.refusal_title)}</div>${quotes}</div>
<div style="display:flex;gap:${GAP}px;margin-top:6px;margin-bottom:-6px">${cards}</div>
<div>${rows}</div>
<div style="font-size:34px;line-height:1.3;font-weight:700;color:${palette.accent}">${esc(spec.footer)}</div></div>`);
};

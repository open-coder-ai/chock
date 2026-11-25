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
  const D = !!spec.dense, T = D ? 64 : 78, f = (n) => (D ? +(n * 0.9).toFixed(1) : n);
  if (D) base.harness.dense = true;
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
  const cropH = T + L.Ht + 20 + (D ? 44 : 56);
  const frame = where((body) => body, base, palette);
  const overlay = `<div style="position:absolute;left:20px;top:${T}px;width:840px;height:${L.Ht}px">${dim}<svg width="840" height="${L.Ht}" style="position:absolute;left:0;top:0" xmlns="http://www.w3.org/2000/svg"><defs>${marker}</defs>${lines}</svg>${steps}${rings}</div>`;
  const row = (mark, text, round, bg = RED) => `<div style="display:flex;gap:10px;align-items:flex-start;margin-top:8px"><span style="flex:none;width:20px;height:20px;line-height:20px;text-align:center;font-size:12px;font-weight:700;color:#fff;background:${bg};border-radius:${round ? '50%' : '4px'}">${mark}</span><span style="font-size:14px;line-height:20px;color:${INK}">${esc(text)}</span></div>`;
  const key = spec.steps.map((s, i) => row(i + 1, s.text, true)).join('') + spec.rings.map((r, i) => row(String.fromCharCode(65 + i), r.label, false)).join('') + spec.dashed.map((r, i) => row(String.fromCharCode(65 + nR + i), r.label, false)).join('') + backstop.map((r, i) => row(String.fromCharCode(65 + nR + nD + i), r.label, false, SOFT)).join('') + (spec.dashed.length ? `<div style="margin-top:10px;font-size:13px;color:${SOFT}">solid ring: a check the proof ran and recorded. dashed ring: a place a rule can be added.</div>` : '');
  const lc = (t) => t.replace(/\.$/, '').replace(/^([A-Z])([a-z])/, (m, x, y) => x.toLowerCase() + y);
  const mk = (mark, round, bg = RED) => `<span style="display:inline-block;width:18px;height:18px;line-height:18px;margin-right:5px;text-align:center;font-size:11px;font-weight:700;color:#fff;background:${bg};border-radius:${round ? '50%' : '4px'}">${mark}</span>`;
  const inl = (head, items) => `<div style="margin-top:4px;font-size:${f(14)}px;line-height:24px;color:${INK}">${head}${items.join(', ')}</div>`;
  const ringItems = [...spec.rings.map((r) => [r, RED]), ...spec.dashed.map((r) => [r, RED]), ...backstop.map((r) => [r, SOFT])].map(([r, bg], i) => mk(String.fromCharCode(65 + i), false, bg) + esc(r.label));
  const denseKey = inl(`<b style="font-size:${f(12)}px;letter-spacing:.06em;color:${SOFT}">${esc(spec.path.title).toUpperCase()}:</b> `, spec.steps.map((s, i) => mk(i + 1, true) + esc(lc(s.text)))) + inl('', ringItems) + `<div style="margin-top:6px;font-size:${f(13)}px;color:${SOFT}">solid ring: a check the proof ran and recorded. dashed ring: a place a rule can be added.</div>`;
  const quotes = (spec.quotes || []).map((q) => `<div style="margin-top:${D ? 6 : 10}px"><div style="font-size:${f(15)}px;line-height:${D ? 20 : 22}px;color:${INK}">\u201C${esc(q.text)}\u201D</div>${q.note ? `<div style="margin-top:4px;font-size:${f(13)}px;font-weight:700;color:${RED}">${esc(q.note)}</div>` : ''}</div>`).join('');
  const refusals = quotes ? quotes : spec.refusals.length
    ? spec.refusals.map((r) => `<div style="margin-top:10px"><div style="font-size:13px;font-weight:700;color:${SOFT}">${esc(r.sample)}: exit ${esc(r.exit)}</div><pre class="mono" style="margin:4px 0 0;white-space:pre-wrap;font-size:13px;line-height:1.5;color:${INK}">${esc(r.text)}</pre></div>`).join('')
    : `<div class="mono" style="margin-top:10px;font-size:13px;color:${SOFT}">no proof recorded yet</div>`;
  return page(`<div id="incident" style="width:880px;background:${PAPER};color:${INK};position:relative">
<div style="position:relative;width:880px;height:${cropH}px;overflow:hidden">${frame}${overlay}</div>
<div style="padding:0 40px ${D ? 14 : 20}px">${D ? denseKey : `<div style="font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:${SOFT}">${esc(spec.path.title)}</div>${key}`}
<div style="margin-top:${D ? 10 : 16}px;padding:${D ? '9px 13px' : '12px 16px'};border:1.5px solid ${LINE};border-radius:12px;background:${palette.chip}"><div style="font-size:${f(12)}px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:${SOFT}">${esc(spec.refusal_title)}</div>${refusals}</div>
<div style="margin-top:${D ? 10 : 16}px;${spec.footer_accent ? `font-size:${f(20)}px;line-height:1.35;font-weight:700;color:${palette.accent}` : `font-size:${f(16)}px;color:${SOFT}`}">${esc(spec.footer)}</div></div></div>`);
};

// The README "which agents" picture: one card per agent, one chip per way Chock holds. Every word and count comes from agents.json (agents_data.py); positions are computed here, and `layout` reports every shape so a test can check nothing overlaps.
import { DEFAULT_PALETTE, SITE_PALETTE } from './where-chock-sits.mjs';

const PAD = 12, CG = 6, RG = 6, GAP = 4, PER = 6.2, CH = 16, MAXLINES = 2;
const COLS = { name: 120, ci: 78, git: 134, hook: 196, plugin: 94, rule: 158 };
const lines = (text, width) => Math.max(1, Math.ceil((text.length * PER + 22) / width));

export const layout = (W) => {
  const shapes = [], cells = [], bad = [];
  const add = (id, x, y, w, h) => shapes.push({ id, x, y, w, h });
  const ids = ['name', ...W.columns.map((c) => c.id)];
  const xs = {}; let x = PAD;
  ids.forEach((id) => { xs[id] = x; x += COLS[id] + CG; });
  const head = { y: 20 * Math.ceil((W.summary.length * 7) / 840) + 22 };
  let y = head.y + 26, last = null;
  const groups = [];
  W.rows.forEach((r) => {
    if (r.plugin !== last) {
      if (last !== null) y += 8;
      const n = W.rows.filter((q) => q.plugin === r.plugin).length;
      groups.push({ text: `${W.groups[r.plugin]} (${n})`, y });
      add(`group-${groups.length}`, 6, y, 300, 14);
      y += 22; last = r.plugin;
    }
    const n = Math.max(1, ...W.columns.map((c) => (r[c.id] ? lines(r[c.id], COLS[c.id]) : 1)));
    if (n > MAXLINES) bad.push([r.id, 'too many lines']);
    const h = 12 + n * CH + (n > 1 ? 2 : 0);
    add(`row-${r.id}`, 0, y, 840, h);
    if (lines(r.name, COLS.name) > 1) bad.push([r.id, 'name-text']);
    W.columns.forEach((c) => { if (r[c.id]) cells.push({ r, c, x: xs[c.id] - 2, y: y + 4, w: COLS[c.id] + 4, h: h - 8, lines: lines(r[c.id], COLS[c.id]) }); });
    r.y = y; r.h = h;
    y += h + RG;
  });
  const lg = y + 14;
  const Ht = lg + 22 * (1 + W.legend.length) + 34;
  return { shapes, cells, groups, xs, head, legendTop: lg, Ht, bad };
};

// Row cards closer than their gap, cells too tall for their lines, text that does not fit a column.
export const crowded = (L) => {
  const bad = [...L.bad], near = (a, b) => a.x < b.x + b.w + 2 && b.x < a.x + a.w + 2 && a.y < b.y + b.h + 2 && b.y < a.y + a.h + 2;
  L.shapes.forEach((a, i) => L.shapes.slice(i + 1).forEach((b) => { if (near(a, b)) bad.push([a.id, b.id]); }));
  L.cells.forEach((c, i) => L.cells.slice(i + 1).forEach((d) => { if (near({ ...c, x: c.x + 2, w: c.w - 4 }, { ...d, x: d.x + 2, w: d.w - 4 })) bad.push([c.r.id + c.c.id, d.r.id + d.c.id]); }));
  L.cells.forEach((c) => { if (c.lines > MAXLINES) bad.push([c.r.id + c.c.id, 'cell-text']); });
  return bad;
};

export const where = (page, W, palette = DEFAULT_PALETTE) => {
  const L = layout(W), bad = crowded(L);
  if (bad.length) throw new Error(`figure shapes too close: ${JSON.stringify(bad)}`);
  const { ink: INK, soft: SOFT, line: LINE, paper: PAPER, accent: ACCENT, grey: GREY, chip: CHIP, hollow: HOLLOW, fill: FILL } = palette;
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const abs = (x, y, w, h, css, inner) => `<div style="position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;${css}">${inner}</div>`;
  const diamond = (x, y, hard, s = 10) => abs(x - s / 2, y - s / 2, s, s, `transform:rotate(45deg);box-sizing:border-box;border:2px solid ${hard ? ACCENT : GREY};background:${hard ? ACCENT : PAPER}`, '');
  const kinds = [...new Set(W.rows.map((r) => r.plugin))], tones = [FILL.context, FILL.subagents, FILL.tools];
  const fill = Object.fromEntries(kinds.map((k, i) => [k, tones[i]]));
  const rows = W.rows.map((r) => abs(0, r.y, 840, r.h, `box-sizing:border-box;background:${fill[r.plugin]};border:1.5px solid ${LINE};border-radius:12px`,
    abs(L.xs.name, 0, COLS.name, r.h, `display:flex;align-items:center;font-size:14px;font-weight:700;line-height:18px;color:${INK};white-space:nowrap`, esc(r.name)))).join('');
  const chip = (k) => abs(k.x, k.y, k.w, k.h, `box-sizing:border-box;display:flex;align-items:center;gap:4px;padding:0 5px;border-radius:${k.lines > 1 ? 10 : 999}px;background:${CHIP};font-size:12px;line-height:${CH}px;font-weight:600;color:${k.c.hard ? ACCENT : INK}`,
    `<span style="position:relative;flex:none;width:10px;height:10px">${diamond(5, 5, k.c.hard)}</span><span style="color:${k.c.hard ? ACCENT : INK}">${esc(k.r[k.c.id])}</span>`);
  const heads = W.columns.map((c) => abs(L.xs[c.id] + 4, L.head.y, COLS[c.id], 18, `font-size:12px;font-weight:700;letter-spacing:.04em;line-height:18px;color:${SOFT};white-space:nowrap`, esc(c.label))).join('');
  const groups = L.groups.map((g) => abs(6, g.y, 400, 14, `font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:${SOFT};white-space:nowrap`, esc(g.text))).join('');
  const legend = W.legend.map((t, i) => abs(0, L.legendTop + 22 + i * 22, 840, 18, `font-size:13px;font-weight:600;color:${SOFT};white-space:nowrap`, esc(t))).join('');
  const total = L.Ht;
  return page(`<div class="frame" style="width:880px;padding:20px;background:${PAPER};color:${INK};position:relative;height:${total + 98}px">
<div style="position:absolute;left:20px;top:20px;width:840px;font-size:20px;line-height:1.35;font-weight:600">${esc(W.title)}</div>
<div style="position:absolute;left:20px;top:78px;width:840px;height:${total}px">
${abs(0, 0, 840, L.head.y - 8, `font-size:14px;line-height:20px;color:${SOFT}`, esc(W.summary))}
${heads}${groups}${rows}${L.cells.map(chip).join('')}
<div class="eyebrow" style="position:absolute;left:0;top:${L.legendTop}px;font-size:13px;color:${ACCENT}">${esc(W.legend_title)}</div>
${legend}
<div style="position:absolute;left:0;top:${total - 26}px;font-size:13px;color:${SOFT}">${esc(W.footer)}</div>
</div></div>`);
};

export { DEFAULT_PALETTE, SITE_PALETTE };

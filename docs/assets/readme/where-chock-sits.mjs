// The README figure: a coding agent's harness as component cards in layers, with the hooks drawn ON the card they belong to. Every word comes from where-chock-sits.json; positions are computed here, and `layout` reports every shape so a test can check nothing overlaps.
const HW = 680, PAD = 16, COLS = 4, G = 62, CW = (HW - 2 * PAD - (COLS - 1) * G) / COLS, VG = 56, GAP = 12;
const RX = 704, RW = 136, RCW = RW - 32;
const col = (c) => PAD + c * (CW + G);
const lines = (text, width, per = 6.4) => Math.max(1, Math.ceil((text.length * per) / width));
const badgeH = () => 20;

export const layout = (W) => {
  const H = W.harness, shapes = [], segs = [], cards = {}, badges = [];
  const D = !!H.dense, sc = D ? 0.9 : 1, vg = D ? 44 : VG, bH = D ? 18 : badgeH(), bp = D ? 4 : 8;
  const add = (id, x, y, w, h) => shapes.push({ id, x, y, w, h });
  const mine = (id) => W.points.filter((p) => p.on === id);
  const size = (c, width) => {
    const bs = mine(c.id);
    c.w = width;
    c.nameH = lines(c.name, width - 16, 8.2 * sc) * 18 * sc;
    c.lineH = lines(c.line, width - 16, 7.8 * sc) * 16 * sc;
    c.badgeH = bs.reduce((a, p) => a + bH + 4, bs.length ? bp : 0);
    c.h = (D ? 8 : 12) + c.nameH + 4 + c.lineH + c.badgeH + bp;
  };
  H.cards.forEach((c) => size(c, c.span * CW + (c.span - 1) * G));
  const rowH = [0, 1, 2].map((r) => Math.max(...H.cards.filter((c) => c.row === r).map((c) => c.h)));
  const rowTop = []; let y = D ? 50 : 56;
  rowH.forEach((h, r) => { if (r < 3) y += r ? 0 : 0; rowTop[r] = y; y += h + vg; });
  const layerTitleY = [rowTop[0] - 30, rowTop[1] - 30, rowTop[2] - 30];
  H.layers.forEach((t, i) => add(`layer-${i}`, PAD + 6, layerTitleY[i], t.length * 8 + 4, 14));
  H.cards.forEach((c) => { c.x = col(c.col); c.y = rowTop[c.row]; cards[c.id] = c; add(`card-${c.id}`, c.x, c.y, c.w, c.h); });
  H.cards.forEach((c) => { let by = c.y + c.h - bp; [...mine(c.id)].reverse().forEach((p) => { const bh = bH; by -= bh; badges.push({ p, x: c.x + 4, y: by, w: c.w - 8, h: bh }); by -= 4; }); });
  // repository cards, top to bottom
  let ry = D ? 90 : 100;
  H.repo_cards.forEach((c) => { size(c, RCW); c.x = RX + 16; c.y = ry; add(`card-${c.id}`, c.x, c.y, c.w, c.h); cards[c.id] = c; ry += c.h + 34; badges.push(...(() => { let by = c.y + c.h - bp; return mine(c.id).map((p) => { const bh = bH; by -= bh; const b = { p, x: c.x + 4, y: by, w: c.w - 8, h: bh }; by -= 4; return b; }); })()); });
  const A = H.arrows, mid = (c) => c.x + c.w / 2, rt = (c) => c.x + c.w, bt = (c) => c.y + c.h, ln = (id, y0 = 26) => cards[id].y + y0;
  const label = (id, text, x, y, w, anchor = 'center') => { const lw = Math.ceil(text.length * 6 + 2); const lx = anchor === 'center' ? x - lw / 2 : anchor === 'right' ? x - lw : x; add(`label-${id}`, lx, y, lw, 14); return { text, x: lx, y, w: lw }; };
  const labels = [];
  const seg = (d, tail = true, both = false) => segs.push({ d, tail, both });
  const { you, prompt, session, context, loop, model, subagents, gate, tools, external, commit, push, ci, main } = cards;
  seg(`M${rt(you)} ${ln('you')} H${prompt.x}`); labels.push(label('you-prompt', A['you-prompt'], (rt(you) + prompt.x) / 2, ln('you') - 22));
  seg(`M${prompt.x + prompt.w / 2} ${bt(prompt)} V${loop.y}`); labels.push(label('prompt-loop', A['prompt-loop'], prompt.x + prompt.w / 2 + 10, (bt(prompt) + loop.y) / 2 - 7, 0, 'left'));
  seg(`M${mid(session)} ${bt(session)} V${loop.y}`); labels.push(label('session-loop', A['session-loop'], mid(session) + 10, (bt(session) + loop.y) / 2 - 7, 0, 'left'));
  seg(`M${rt(context)} ${ln('context')} H${loop.x}`); labels.push(label('context-loop', A['context-loop'], (rt(context) + loop.x) / 2, ln('context') - 22));
  seg(`M${rt(loop)} ${ln('loop')} H${model.x}`, true, true); labels.push(label('loop-model', A['loop-model'], (rt(loop) + model.x) / 2, ln('loop') - 22));
  const xa = gate.x + 10, xb = gate.x + gate.w - 10, ym = (bt(loop) + gate.y) / 2 - 7;
  seg(`M${xa} ${bt(loop)} V${gate.y}`); labels.push(label('loop-gate', A['loop-gate'], mid(gate), ym));
  seg(`M${xb} ${gate.y} V${bt(loop)}`); labels.push(label('gate-loop', A['gate-loop'], xb + 10, ym, 0, 'left'));
  seg(`M${rt(gate)} ${ln('gate')} H${tools.x}`); labels.push(label('gate-tools', A['gate-tools'], (rt(gate) + tools.x) / 2, ln('gate') - 22));
  seg(`M${mid(tools)} ${tools.y} V${bt(loop)}`); labels.push(label('tools-loop', A['tools-loop'], mid(tools) + 10, ym, 0, 'left'));
  seg(`M${rt(tools)} ${ln('tools')} H${external.x}`); labels.push(label('tools-external', A['tools-external'], (rt(tools) + external.x) / 2, ln('tools') - 22));
  const gx = rt(context) + G / 2, sy = ln('subagents');
  seg(`M${loop.x} ${loop.y + loop.h - 28} H${gx} V${sy} H${rt(subagents)}`); labels.push(label('loop-subagents', A['loop-subagents'], gx - 10, (bt(context) + subagents.y) / 2 - 7, 0, 'right'));
  const wx = HW + 12;
  const yb = rowTop[2] + rowH[2] + 22;
  seg(`M${mid(tools)} ${bt(tools)} V${yb} H${wx} V${ln('commit')} H${commit.x}`); labels.push(label('tools-commit', A['tools-commit'], (mid(tools) + wx) / 2, yb + 8));
  [[commit, push], [push, ci], [ci, main]].forEach(([u, v]) => seg(`M${mid(u)} ${bt(u)} V${v.y}`));
  const Ht = Math.max(rowTop[2] + rowH[2] + (D ? 54 : 56), ry + 6);
  return { shapes, segs, cards, badges, labels, rowTop, layerTitleY, Ht, wx, ry };
};

// Cards, labels and badges closer than GAP; a label too near an arrow line.
export const crowded = (L) => {
  const bad = [], near = (a, b, g = GAP) => a.x < b.x + b.w + g && b.x < a.x + a.w + g && a.y < b.y + b.h + g && b.y < a.y + a.h + g;
  L.shapes.forEach((a, i) => L.shapes.slice(i + 1).forEach((b) => { if (near(a, b)) bad.push([a.id, b.id]); }));
  L.badges.forEach((b) => L.shapes.filter((s) => s.id.startsWith('label-')).forEach((s) => { if (near(b, s)) bad.push([b.p.id, s.id]); }));
  L.badges.forEach((b) => { if (b.p.label.length * 6.1 + 20 > b.w) bad.push([b.p.id, 'badge-text']); });
  L.badges.forEach((b, i) => L.badges.slice(i + 1).forEach((c) => { if (near(b, c, 2)) bad.push([b.p.id, c.p.id]); }));
  const points = (d) => { const n = [...d.matchAll(/([MHV])(-?[\d.]+)(?: (-?[\d.]+))?/g)]; let x = 0, y = 0; const out = []; n.forEach((m) => { if (m[1] === 'M') { x = +m[2]; y = +m[3]; } else if (m[1] === 'H') x = +m[2]; else y = +m[2]; out.push([x, y]); }); return out; };
  const hit = (r, i) => r.x <= i.x + i.w && i.x <= r.x + r.w && r.y <= i.y + i.h && i.y <= r.y + r.h;
  L.segs.forEach((s) => { const p = points(s.d); p.slice(1).forEach((q, i) => { const a = p[i], r = { x: Math.min(a[0], q[0]), y: Math.min(a[1], q[1]), w: Math.abs(q[0] - a[0]), h: Math.abs(q[1] - a[1]) };
    L.shapes.filter((c) => c.id.startsWith('card-')).forEach((c) => { if (hit(r, { x: c.x + 2, y: c.y + 2, w: c.w - 4, h: c.h - 4 })) bad.push([s.d, c.id]); });
    L.shapes.filter((l) => l.id.startsWith('label-')).forEach((l) => { if (near(l, r, 6)) bad.push([s.d, l.id]); }); }); });
  return bad;
};

// A palette is a small object of named colours; the layout never reads it, so every palette gives the same shapes.
export const DEFAULT_PALETTE = {
  paper: '#FBF7EE', ink: '#2B2A35', soft: '#5C5A6B', line: '#6B6877', accent: '#C2410C', grey: '#8D8A99',
  chip: '#fff', hollow: '#7C7989',
  fill: { you: '#EFE9F9', prompt: '#EFE9F9', session: '#EFE9F9', context: '#DDEFE0', loop: '#DCEAF9', model: '#E8E1F6', subagents: '#F6E2EC', gate: '#F6E2EC', tools: '#ECE6D8', external: '#E9E4F3', commit: '#DDF0EE', push: '#DDF0EE', ci: '#DDF0EE', main: '#DDF0EE' },
};
// The chock-site palette: the tokens in chock-site static/css/site.css (--bg, --text, --body, --line-2, --accent, --muted, --footer-bg).
export const SITE_PALETTE = {
  paper: '#0B1B33', ink: '#FFFFFF', soft: '#C7D2E3', line: '#607198', accent: '#38BDF8', grey: '#94A3B8',
  chip: '#081326', hollow: '#94A3B8',
  fill: { you: '#1B2F55', prompt: '#1B2F55', session: '#1B2F55', context: '#113A44', loop: '#16365E', model: '#2A2856', subagents: '#3A2647', gate: '#3A2647', tools: '#24324F', external: '#2A2856', commit: '#0E3B42', push: '#0E3B42', ci: '#0E3B42', main: '#0E3B42' },
};

export const where = (page, W, palette = DEFAULT_PALETTE) => {
  const L = layout(W), bad = crowded(L), H = W.harness, D = !!H.dense, fs = (n) => `${D ? +(n * 0.9).toFixed(1) : n}px`;
  if (bad.length) throw new Error(`figure shapes too close: ${JSON.stringify(bad)}`);
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const { ink: INK, soft: SOFT, line: LINE, paper: PAPER, accent: ACCENT, grey: GREY, chip: CHIP, hollow: HOLLOW, fill: FILL } = palette;
  const abs = (x, y, w, h, css, inner) => `<div style="position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;${css}">${inner}</div>`;
  const diamond = (x, y, acts, s = 10) => abs(x - s / 2, y - s / 2, s, s, `transform:rotate(45deg);box-sizing:border-box;border:2px solid ${acts ? ACCENT : GREY};background:${acts ? ACCENT : PAPER}`, '');
  const frame = (x, y, w, h, title, inside = false) => abs(x, y, w, h, `border:2px dashed ${LINE};border-radius:18px;box-sizing:border-box`, inside ? `<div style="position:absolute;left:14px;top:10px;width:${w - 28}px;font-size:${fs(14)};font-weight:700;line-height:18px;color:${INK}">${esc(title)}</div>` : `<div style="position:absolute;left:16px;top:-13px;padding:0 8px;background:${PAPER};font-size:${fs(14)};font-weight:700;color:${INK};white-space:nowrap">${esc(title)}</div>`);
  const card = (c) => abs(c.x, c.y, c.w, c.h, `box-sizing:border-box;background:${FILL[c.id]};border:1.5px solid ${LINE};border-radius:12px;padding:${D ? 6 : 10}px 8px`, `<div style="font-size:${fs(14)};font-weight:700;line-height:18px;color:${INK}">${esc(c.name)}</div><div style="font-size:${fs(12.5)};line-height:16px;color:${SOFT};margin-top:4px">${esc(c.line)}</div>`);
  const badge = (b) => abs(b.x, b.y, b.w, b.h, `box-sizing:border-box;display:flex;align-items:center;gap:4px;padding:0 5px;border-radius:999px;background:${CHIP};white-space:nowrap;font-size:${fs(12)};line-height:14px;font-weight:600;color:${b.p.acts ? ACCENT : HOLLOW}`, `<span style="position:relative;flex:none;width:10px;height:10px">${diamond(5, 5, b.p.acts)}</span><span>${esc(b.p.label)}</span>`);
  const arrow = `<marker id="g" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M1 1 L9 5 L1 9" fill="none" stroke="${LINE}" stroke-width="1.7"/></marker><marker id="s" markerWidth="10" markerHeight="10" refX="2" refY="5" orient="auto"><path d="M9 1 L1 5 L9 9" fill="none" stroke="${LINE}" stroke-width="1.7"/></marker>`;
  const paths = L.segs.map((s) => `<path d="${s.d}" fill="none" stroke="${LINE}" stroke-width="1.8" marker-end="url(#g)"${s.both ? ' marker-start="url(#s)"' : ''}/>`).join('');
  const layerTitles = H.layers.map((t, i) => abs(PAD + 6, L.layerTitleY[i], 120, 14, `font-size:${fs(12)};font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:${SOFT}`, esc(t))).join('');
  const labels = L.labels.map((l) => abs(l.x, l.y, l.w, 14, `font-size:${fs(12)};line-height:14px;font-weight:600;color:${SOFT};white-space:nowrap`, esc(l.text))).join('');
  const keyRow = (acts, text, y) => `<div style="position:absolute;left:0;top:${y}px;font-size:${fs(13)};font-weight:600;color:${SOFT};display:flex;align-items:center;gap:12px"><span style="position:relative;width:14px;height:14px;display:inline-block">${diamond(7, 7, acts, 12)}</span>${esc(text)}</div>`;
  const stop = `padding:4px 6px;border:1.5px solid ${LINE};border-radius:999px;background:${CHIP};font-size:12.5px;font-weight:600;color:${INK};white-space:nowrap`;
  const own = `<span style="display:inline-flex;flex-direction:column;align-items:center;gap:1px;padding:3px 8px;border:1.5px dashed ${ACCENT};border-radius:14px;color:${ACCENT};font-size:12.5px;font-weight:700;white-space:nowrap">${esc(W.own.label)}<span class="mono" style="font-size:12px;font-weight:500;color:${INK}">${esc(W.own.command)}</span></span>`;
  const stops = W.stops.map((s) => `<span style="${stop}">${esc(s)}</span>`).join('') + own;
  const base = L.Ht + 20, total = base + 196;
  return page(`<div class="frame" style="width:880px;padding:20px;background:${PAPER};color:${INK};position:relative;height:${total + 110}px">
<div style="position:absolute;left:20px;top:20px;width:840px;font-size:${fs(20)};line-height:1.35;font-weight:600">${esc(H.title)}</div>
<div style="position:absolute;left:20px;top:${D ? 64 : 78}px;width:840px;height:${total}px">
${frame(0, 0, HW, L.Ht, H.frame)}${frame(RX, 0, RW, L.Ht, H.repo_frame, true)}
<svg width="840" height="${L.Ht}" style="position:absolute;left:0;top:0" xmlns="http://www.w3.org/2000/svg"><defs>${arrow}</defs>${paths}</svg>
${layerTitles}${[...H.cards, ...H.repo_cards].map(card).join('')}${L.badges.map(badge).join('')}${labels}
${keyRow(true, H.key.acts, base)}${keyRow(false, H.key.exposed, base + 28)}
<div class="eyebrow" style="position:absolute;left:0;top:${base + 70}px;font-size:14px;color:${ACCENT}">${esc(W.stops_title)}</div>
<div style="position:absolute;left:0;top:${base + 98}px;width:840px;display:flex;flex-wrap:nowrap;align-items:center;gap:5px">${stops}</div>
<div style="position:absolute;left:0;top:${base + 166}px;font-size:16px;color:${SOFT}">${esc(W.footer)}</div>
</div></div>`);
};

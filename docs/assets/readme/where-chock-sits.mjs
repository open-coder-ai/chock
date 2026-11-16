// The README "How it works" figure: a session as an ordered path with checkpoints. Every word comes from where-chock-sits.json; positions are computed here by a flow layout, and `layout` also reports every shape so a test can check nothing overlaps.
const R = 14, TEXT_W = 84, DIAMOND = 20, GAP = 12;
const LINES = (text, perLine = 11) => Math.ceil(text.length / perLine);

export const layout = (W) => {
  const shapes = [], arrows = [], diamonds = [];
  const add = (id, x, y, w, h) => shapes.push({ id, x, y, w, h });
  const rows = {};
  const place = (key, x0, x1, y, T) => {
    const steps = W.paths[key].steps;
    const pts = W.points.filter((p) => p.place?.row === key);
    const weight = steps.map((_, k) => Math.max(1, ...pts.filter((p) => p.place.into === k).map((p) => (p.place.of > 1 ? p.place.of + 1 : 1))));
    const free = x1 - x0 - steps.length * 2 * R, unit = free / weight.reduce((a, b) => a + b, 0);
    let cursor = x0;
    const cx = steps.map((_, k) => { const start = cursor; cursor += weight[k] * unit + 2 * R; arrows.push({ key, k, x1: start, x2: start + weight[k] * unit + R, y }); return start + weight[k] * unit + R; });
    steps.forEach((s, k) => {
      const lines = LINES(s.text) + (s.sub ? LINES(s.sub, 13) : 0);
      s.h = lines * 16 + 6;
      add(`${key}-circle-${k}`, cx[k] - R, y - R, 2 * R, 2 * R);
      add(`${key}-text-${k}`, cx[k] - TEXT_W / 2, y + R + 8, TEXT_W, s.h);
    });
    pts.forEach((p) => {
      const a = arrows.find((q) => q.key === key && q.k === p.place.into);
      const x = a.x1 + ((a.x2 - R - a.x1) * (p.place.slot + 1)) / (p.place.of + 1), w = p.place.of > 1 ? 56 : 80;
      diamonds.push({ id: p.id, x, y, acts: p.acts });
      add(`${p.id}-diamond`, x - DIAMOND / 2, y - DIAMOND / 2, DIAMOND, DIAMOND);
      if (p.acts) add(`${p.id}-does`, x - w / 2, y - 30 - 32, w, 32);
    });
    rows[key] = { cx, y, T };
  };
  place('agent', 24, 782, 216, 56);
  place('repo', 10, 782, 540, 436);
  const YA = rows.agent.y, tool = rows.agent.cx[4], mcp = W.points.find((p) => p.place?.tag);
  add('tag', tool - 76, YA + 108, 152, 24);
  add('tag-diamond', tool - 76 - DIAMOND / 2, YA + 108 + 12 - DIAMOND / 2, DIAMOND, DIAMOND);
  diamonds.push({ id: mcp.id, x: tool - 76, y: YA + 120, acts: mcp.acts });
  add('tag-does', tool - 50, YA + 146, 100, 16);
  const loop = W.paths.agent.loop, xt = rows.agent.cx[loop.from], xm = rows.agent.cx[loop.to], y0 = YA - R, peak = 96;
  const c = peak * 1.33;
  const curve = Array.from({ length: 51 }, (_, i) => { const t = i / 50, u = 1 - t; return [u ** 3 * xt + 3 * u * u * t * (xt + 40) + 3 * u * t * t * (xm - 40) + t ** 3 * xm, u ** 3 * y0 + 3 * u * u * t * (y0 - c) + 3 * u * t * t * (y0 - c) + t ** 3 * y0]; });
  add('loop-label', (xt + xm) / 2 - 60, y0 - peak - 26, 120, 16);
  return { shapes, arrows, diamonds, rows, curve, loop: { xt, xm, y0, peak, c } };
};

// Pairs of shapes closer than GAP, the loop arrow passing a label, and arrows with a shaft under 40 px.
export const crowded = (L) => {
  const bad = [];
  const near = (a, b) => a.x < b.x + b.w + GAP && b.x < a.x + a.w + GAP && a.y < b.y + b.h + GAP && b.y < a.y + a.h + GAP;
  const own = (a, b) => (a.id.split('-diamond')[0] === b.id.split('-does')[0] && a.id.endsWith('-diamond') && b.id.endsWith('-does')) || (a.id.replace('-circle-', '-text-') === b.id && a.id.includes('-circle-')) || (a.id === 'tag' && b.id === 'tag-diamond');
  L.shapes.forEach((a, i) => L.shapes.slice(i + 1).forEach((b) => { if (!own(a, b) && !own(b, a) && near(a, b)) bad.push([a.id, b.id]); }));
  L.shapes.filter((s) => s.id.endsWith('-does') || s.id === 'loop-label').forEach((s) => { if (L.curve.some(([x, y]) => x > s.x - 8 && x < s.x + s.w + 8 && y > s.y - 8 && y < s.y + s.h + 8)) bad.push([s.id, 'loop-arrow']); });
  L.arrows.forEach((a) => { if (a.x2 - R - a.x1 - 8 < 40) bad.push([`${a.key}-arrow-${a.k}`, 'short']); });
  return bad;
};

export const where = (page, W) => {
  const L = layout(W), bad = crowded(L);
  if (bad.length) throw new Error(`figure shapes too close: ${JSON.stringify(bad)}`);
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const INK = '#2B2A35', SOFT = '#5C5A6B', LINE = '#6B6877', PAPER = '#FBF7EE', ACCENT = '#C2410C', GREY = '#8D8A99';
  const abs = (x, y, w, h, css, inner) => `<div style="position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;${css}">${inner}</div>`;
  const diamond = (x, y, acts, s = 14) => abs(x - s / 2, y - s / 2, s, s, `transform:rotate(45deg);box-sizing:border-box;border:2px solid ${acts ? ACCENT : GREY};background:${acts ? ACCENT : PAPER}`, '');
  const note = (s, text) => abs(s.x, s.y, s.w, s.h, `font-size:12.5px;line-height:1.25;font-weight:600;color:${ACCENT};text-align:center;display:flex;align-items:flex-end;justify-content:center`, esc(text));
  const frame = (y, h, name) => abs(0, y, 840, h, `border:2px dashed ${LINE};border-radius:18px;box-sizing:border-box`, `<div style="position:absolute;left:20px;top:8px;font-size:14px;font-weight:700;color:${INK}">${esc(name)}</div>`);
  const head = `<marker id="g" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M1 1 L9 5 L1 9" fill="none" stroke="${LINE}" stroke-width="1.7"/></marker>`;
  const line = (d) => `<path d="${d}" fill="none" stroke="${LINE}" stroke-width="1.8" marker-end="url(#g)"/>`;
  const { xt, xm, y0, peak, c } = L.loop, ya = L.rows.agent.y, yr = L.rows.repo.y, last = L.rows.agent.cx[5];
  const entry = L.arrows.find((a) => a.key === 'repo' && a.k === 0);
  const paths = [
    ...L.arrows.map((a) => line(`M${a.x1} ${a.y} H${a.x2 - R}`)),
    line(`M${xt} ${y0} C${xt + 40} ${y0 - c} ${xm - 40} ${y0 - c} ${xm} ${y0 - 2}`),
    line(`M${last + R} ${ya} H828 V418 H10 V${yr} H${entry.x2 - R}`),
  ].join('');
  const stepHtml = (key) => W.paths[key].steps.map((s, k) => {
    const cx = L.rows[key].cx[k], y = L.rows[key].y, n = key === 'agent' ? k + 1 : k + 7;
    return abs(cx - R, y - R, 2 * R, 2 * R, `box-sizing:border-box;border:2px solid ${LINE};border-radius:50%;background:#fff;font-size:13px;font-weight:700;display:flex;align-items:center;justify-content:center`, n)
      + abs(cx - TEXT_W / 2, y + R + 8, TEXT_W, s.h, `text-align:center;font-size:13.5px;line-height:16px;font-weight:600;color:${INK}`, `${esc(s.text)}${s.sub ? `<div style="font-weight:500;color:${SOFT}">${esc(s.sub)}</div>` : ''}`);
  }).join('');
  const marks = W.points.filter((p) => p.place?.row || p.place?.tag).map((p) => {
    const d = L.diamonds.find((q) => q.id === p.id), s = L.shapes.find((q) => q.id === (p.place.tag ? 'tag-does' : `${p.id}-does`));
    return diamond(d.x, d.y, p.acts) + (p.acts && s ? note(s, p.does) : '');
  }).join('');
  const tagHtml = abs(L.rows.agent.cx[4] - 76, ya + 108, 152, 24, `box-sizing:border-box;border:1.5px solid ${LINE};border-radius:999px;background:#fff;font-size:12.5px;font-weight:600;color:${INK};display:flex;align-items:center;justify-content:center;padding-left:18px`, esc(W.paths.agent.steps[4].tag));
  const loopLabel = abs((xt + xm) / 2 - 60, y0 - peak - 26, 120, 16, `font-size:12.5px;font-weight:600;color:${SOFT};text-align:center`, esc(W.paths.agent.loop.label));
  const keyRow = (acts, text, y) => `<div style="position:absolute;left:0;top:${y}px;font-size:13px;font-weight:600;color:${SOFT};display:flex;align-items:center;gap:12px"><span style="position:relative;width:14px;height:14px;display:inline-block">${diamond(7, 7, acts)}</span>${esc(text)}</div>`;
  const chip = (p) => `<span style="display:inline-flex;align-items:center;gap:10px;padding:4px 10px 4px 10px;border:1.5px solid ${LINE};border-radius:999px;background:#fff;font-size:12.5px;font-weight:600;color:${INK};white-space:nowrap"><span style="position:relative;width:10px;height:10px;display:inline-block">${diamond(5, 5, p.acts, 10)}</span>${esc(p.label)}</span>`;
  const more = W.points.filter((p) => p.place?.chip).map(chip).join('');
  const stop = `padding:4px 6px;border:1.5px solid ${LINE};border-radius:999px;background:#fff;font-size:12.5px;font-weight:600;color:${INK};white-space:nowrap`;
  const own = `<span style="display:inline-flex;flex-direction:column;align-items:center;gap:1px;padding:3px 8px;border:1.5px dashed ${ACCENT};border-radius:14px;color:${ACCENT};font-size:12.5px;font-weight:700;white-space:nowrap">${esc(W.own.label)}<span class="mono" style="font-size:12px;font-weight:500;color:${INK}">${esc(W.own.command)}</span></span>`;
  const stops = W.stops.map((s) => `<span style="${stop}">${esc(s)}</span>`).join('') + own;
  return page(`<div class="frame" style="width:880px;padding:20px;background:${PAPER};color:${INK};position:relative;height:996px">
<div style="position:absolute;left:20px;top:20px;width:840px;font-size:20px;line-height:1.35;font-weight:600">${esc(W.title)}</div>
<div style="position:absolute;left:20px;top:30px;width:840px;height:960px">
${frame(L.rows.agent.T, 342, W.paths.agent.name)}${frame(L.rows.repo.T, 180, W.paths.repo.name)}
<svg width="840" height="680" style="position:absolute;left:0;top:0" xmlns="http://www.w3.org/2000/svg"><defs>${head}</defs>${paths}</svg>
${stepHtml('agent')}${stepHtml('repo')}${tagHtml}${loopLabel}${marks}
${keyRow(true, W.key.acts, 646)}${keyRow(false, W.key.exposed, 674)}
<div class="eyebrow" style="position:absolute;left:0;top:716px;font-size:14px;color:${LINE}">${esc(W.more_title)}</div>
<div style="position:absolute;left:0;top:742px;width:840px;display:flex;flex-wrap:wrap;gap:8px">${more}</div>
<div class="eyebrow" style="position:absolute;left:0;top:826px;font-size:14px;color:${ACCENT}">${esc(W.stops_title)}</div>
<div style="position:absolute;left:0;top:854px;width:840px;display:flex;flex-wrap:nowrap;align-items:center;gap:5px">${stops}</div>
<div style="position:absolute;left:0;top:922px;font-size:16px;color:${SOFT}">${esc(W.footer)}</div>
</div></div>`);
};

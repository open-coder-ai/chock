// The README "How it works" figure: a session as an ordered path with checkpoints. Every word comes from where-chock-sits.json; positions are computed here by a flow layout, and `layout` also reports every shape so a test can check nothing overlaps.
const R = 14, TEXT_W = 84, DIAMOND = 20, GAP = 12, T1 = 56, YA = 244, H1 = 414, T2 = T1 + H1 + 40, YR = T2 + 104, H2 = 210, TEXT_TOP = 52;
const LINES = (text, perLine = 11) => Math.ceil(text.length / perLine);
const nameW = (s) => Math.ceil(s.length * 6 + 4);

export const layout = (W) => {
  const shapes = [], arrows = [], diamonds = [];
  const add = (id, x, y, w, h) => shapes.push({ id, x, y, w, h });
  const rows = {};
  const label = (p, x, y) => {
    add(`${p.id}-diamond`, x - DIAMOND / 2, y - DIAMOND / 2, DIAMOND, DIAMOND);
    add(`${p.id}-name`, x - nameW(p.label) / 2, y + 26, nameW(p.label), 14);
    if (p.acts) add(`${p.id}-does`, x - (p.place.of > 1 ? 28 : 40), y - 30 - 32, p.place.of > 1 ? 56 : 80, 32);
  };
  const place = (key, x0, x1, y, T) => {
    const steps = W.paths[key].steps;
    const pts = W.points.filter((p) => p.place?.row === key);
    const weight = steps.map((_, k) => Math.max(1, ...pts.filter((p) => p.place.into === k).map((p) => (p.place.of > 1 ? p.place.of + 1.5 : 1))));
    const free = x1 - x0 - steps.length * 2 * R, unit = free / weight.reduce((a, b) => a + b, 0);
    let cursor = x0;
    const cx = steps.map((_, k) => { const start = cursor; cursor += weight[k] * unit + 2 * R; arrows.push({ key, k, x1: start, x2: start + weight[k] * unit + R, y }); return start + weight[k] * unit + R; });
    steps.forEach((s, k) => {
      s.h = (LINES(s.text) + (s.sub ? LINES(s.sub, 13) : 0)) * 16 + 6;
      add(`${key}-circle-${k}`, cx[k] - R, y - R, 2 * R, 2 * R);
      add(`${key}-text-${k}`, cx[k] - TEXT_W / 2, y + TEXT_TOP, TEXT_W, s.h);
    });
    pts.forEach((p) => {
      const a = arrows.find((q) => q.key === key && q.k === p.place.into);
      const x = a.x1 + ((a.x2 - R - a.x1) * (p.place.slot + 1)) / (p.place.of + 1);
      diamonds.push({ id: p.id, x, y, acts: p.acts });
      label(p, x, y);
    });
    rows[key] = { cx, y, T };
  };
  place('agent', 24, 782, YA, T1);
  place('repo', 10, 782, YR, T2);
  const A = rows.agent, tool = A.cx[4], mcp = W.points.find((p) => p.place?.tag), toolText = A.cx.length && W.paths.agent.steps[4].h;
  const lineTop = YA + TEXT_TOP + toolText + 6, mid = lineTop + 28, tagTop = lineTop + 56;
  add('tag', tool - 76, tagTop, 152, 24);
  add(`${mcp.id}-diamond`, tool - DIAMOND / 2, mid - DIAMOND / 2, DIAMOND, DIAMOND);
  add(`${mcp.id}-name`, tool - 22 - nameW(mcp.label) - 8, mid - 7, nameW(mcp.label) + 8, 14);
  add(`${mcp.id}-does`, tool + 14, mid - 8, 90, 16);
  diamonds.push({ id: mcp.id, x: tool, y: mid, acts: mcp.acts });
  const loop = W.paths.agent.loop, post = diamonds.find((d) => d.id === loop.after), next = diamonds.find((d) => d.id === 'stop');
  const xs = (post.x + next.x) / 2, xm = A.cx[loop.to], y0 = YA - R;
  const yv = YA - 110, p1 = [xs, yv - 55], p2 = [xm - 40, y0 - 140], end = [xm, y0 - 2];
  const bez = (t) => { const u = 1 - t; return [u ** 3 * xs + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * end[0], u ** 3 * yv + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * end[1]]; };
  const curve = [...Array.from({ length: 20 }, (_, i) => [xs, YA - 4 - ((YA - 4 - yv) * i) / 19]), ...Array.from({ length: 51 }, (_, i) => bez(i / 50))];
  const loopPath = `M${xs} ${YA - 4} V${yv} C${p1[0]} ${p1[1]} ${p2[0]} ${p2[1]} ${end[0]} ${end[1]}`;
  add('loop-label', (xs + xm) / 2 - 60, YA - 172, 120, 16);
  return { shapes, arrows, diamonds, rows, curve, loop: { xs, xm, y0 }, loopPath, mid, lineTop, tagTop };
};

// Pairs of shapes closer than GAP, the loop arrow passing a label, and arrows with a shaft under 40 px.
export const crowded = (L) => {
  const bad = [];
  const near = (a, b) => a.x < b.x + b.w + GAP && b.x < a.x + a.w + GAP && a.y < b.y + b.h + GAP && b.y < a.y + a.h + GAP;
  const base = (id) => id.replace(/-(diamond|does|name)$/, '');
  const own = (a, b) => (base(a.id) === base(b.id) && a.id !== b.id && /-(diamond|does|name)$/.test(a.id) && /-(diamond|does|name)$/.test(b.id)) || (a.id.replace('-circle-', '-text-') === b.id && a.id.includes('-circle-'));
  L.shapes.forEach((a, i) => L.shapes.slice(i + 1).forEach((b) => { if (!own(a, b) && near(a, b)) bad.push([a.id, b.id]); }));
  L.shapes.filter((s) => /-(does|name)$/.test(s.id) || s.id === 'loop-label').forEach((s) => { if (L.curve.some(([x, y]) => x > s.x - 8 && x < s.x + s.w + 8 && y > s.y - 8 && y < s.y + s.h + 8)) bad.push([s.id, 'loop-arrow']); });
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
  const text = (s, css, inner) => abs(s.x, s.y, s.w, s.h, `font-size:12.5px;line-height:1.25;font-weight:600;text-align:center;${css}`, esc(inner));
  const frame = (y, h, name) => abs(0, y, 840, h, `border:2px dashed ${LINE};border-radius:18px;box-sizing:border-box`, `<div style="position:absolute;left:20px;top:8px;font-size:14px;font-weight:700;color:${INK}">${esc(name)}</div>`);
  const head = `<marker id="g" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M1 1 L9 5 L1 9" fill="none" stroke="${LINE}" stroke-width="1.7"/></marker>`;
  const line = (d, arrow = true) => `<path d="${d}" fill="none" stroke="${LINE}" stroke-width="1.8"${arrow ? ' marker-end="url(#g)"' : ''}/>`;
  const yr = L.rows.repo.y, last = L.rows.agent.cx[5], tool = L.rows.agent.cx[4];
  const entry = L.arrows.find((a) => a.key === 'repo' && a.k === 0), ymid = (T1 + H1 + T2) / 2;
  const paths = [
    ...L.arrows.map((a) => line(`M${a.x1} ${a.y} H${a.x2 - R}`)),
    line(L.loopPath),
    `<circle cx="${L.loop.xs}" cy="${YA - 4}" r="3.5" fill="${LINE}"/>`,
    line(`M${tool} ${L.lineTop} V${L.tagTop}`, false),
    line(`M${last + R} ${YA} H828 V${ymid} H10 V${yr} H${entry.x2 - R}`),
  ].join('');
  const stepHtml = (key) => W.paths[key].steps.map((s, k) => {
    const cx = L.rows[key].cx[k], y = L.rows[key].y, n = key === 'agent' ? k + 1 : k + 7;
    return abs(cx - R, y - R, 2 * R, 2 * R, `box-sizing:border-box;border:2px solid ${LINE};border-radius:50%;background:#fff;font-size:13px;font-weight:700;display:flex;align-items:center;justify-content:center`, n)
      + abs(cx - TEXT_W / 2, y + TEXT_TOP, TEXT_W, s.h, `text-align:center;font-size:13.5px;line-height:16px;font-weight:600;color:${INK}`, `${esc(s.text)}${s.sub ? `<div style="font-weight:500;color:${SOFT}">${esc(s.sub)}</div>` : ''}`);
  }).join('');
  const marks = W.points.filter((p) => p.place?.row || p.place?.tag).map((p) => {
    const d = L.diamonds.find((q) => q.id === p.id), get = (suffix) => L.shapes.find((q) => q.id === `${p.id}-${suffix}`);
    const name = get('name'), does = get('does');
    return diamond(d.x, d.y, p.acts) + text(name, `color:${GREY};font-size:12px;font-weight:600;white-space:nowrap`, p.label) + (p.acts ? text(does, `color:${ACCENT};display:flex;align-items:flex-end;justify-content:center`, p.does) : '');
  }).join('');
  const tagHtml = abs(tool - 76, L.tagTop, 152, 24, `box-sizing:border-box;border:1.5px solid ${LINE};border-radius:999px;background:#fff;font-size:12.5px;font-weight:600;color:${INK};display:flex;align-items:center;justify-content:center`, esc(W.paths.agent.steps[4].tag));
  const loopLabel = text(L.shapes.find((s) => s.id === 'loop-label'), `color:${SOFT}`, W.paths.agent.loop.label);
  const keyRow = (acts, label, y) => `<div style="position:absolute;left:0;top:${y}px;font-size:13px;font-weight:600;color:${SOFT};display:flex;align-items:center;gap:12px"><span style="position:relative;width:14px;height:14px;display:inline-block">${diamond(7, 7, acts)}</span>${esc(label)}</div>`;
  const chip = (p) => `<span style="display:inline-flex;align-items:center;gap:10px;padding:4px 10px;border:1.5px solid ${LINE};border-radius:999px;background:#fff;font-size:12.5px;font-weight:600;color:${INK};white-space:nowrap"><span style="position:relative;width:10px;height:10px;display:inline-block">${diamond(5, 5, p.acts, 10)}</span>${esc(p.label)}</span>`;
  const more = W.points.filter((p) => p.place?.chip).map(chip).join('');
  const stop = `padding:4px 6px;border:1.5px solid ${LINE};border-radius:999px;background:#fff;font-size:12.5px;font-weight:600;color:${INK};white-space:nowrap`;
  const own = `<span style="display:inline-flex;flex-direction:column;align-items:center;gap:1px;padding:3px 8px;border:1.5px dashed ${ACCENT};border-radius:14px;color:${ACCENT};font-size:12.5px;font-weight:700;white-space:nowrap">${esc(W.own.label)}<span class="mono" style="font-size:12px;font-weight:500;color:${INK}">${esc(W.own.command)}</span></span>`;
  const stops = W.stops.map((s) => `<span style="${stop}">${esc(s)}</span>`).join('') + own;
  const base = T2 + H2 + 22;
  return page(`<div class="frame" style="width:880px;padding:20px;background:${PAPER};color:${INK};position:relative;height:${base + 346}px">
<div style="position:absolute;left:20px;top:20px;width:840px;font-size:20px;line-height:1.35;font-weight:600">${esc(W.title)}</div>
<div style="position:absolute;left:20px;top:30px;width:840px;height:${base + 300}px">
${frame(T1, H1, W.paths.agent.name)}${frame(T2, H2, W.paths.repo.name)}
<svg width="840" height="${T2 + H2}" style="position:absolute;left:0;top:0" xmlns="http://www.w3.org/2000/svg"><defs>${head}</defs>${paths}</svg>
${stepHtml('agent')}${stepHtml('repo')}${tagHtml}${loopLabel}${marks}
${keyRow(true, W.key.acts, base)}${keyRow(false, W.key.exposed, base + 28)}
<div class="eyebrow" style="position:absolute;left:0;top:${base + 70}px;font-size:14px;color:${LINE}">${esc(W.more_title)}</div>
<div style="position:absolute;left:0;top:${base + 96}px;width:840px;display:flex;flex-wrap:wrap;gap:8px">${more}</div>
<div class="eyebrow" style="position:absolute;left:0;top:${base + 180}px;font-size:14px;color:${ACCENT}">${esc(W.stops_title)}</div>
<div style="position:absolute;left:0;top:${base + 208}px;width:840px;display:flex;flex-wrap:nowrap;align-items:center;gap:5px">${stops}</div>
<div style="position:absolute;left:0;top:${base + 276}px;font-size:16px;color:${SOFT}">${esc(W.footer)}</div>
</div></div>`);
};

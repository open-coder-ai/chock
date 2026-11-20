// An incident teardown figure in the harness picture's look: cards in dashed frames, the incident's path as a line, the checks that refuse it as diamonds. Every word comes from incident-<slug>.json; positions are computed here and `layout` reports every shape so a test can check nothing overlaps.
import { DEFAULT_PALETTE } from './where-chock-sits.mjs';

const FW = 560, RX = 600, RW = 240, CW = 130, AW = 230, GAP = 8, ROW1 = 40;
const lines = (text, width, per = 6.4) => text.split('\n').reduce((n, t) => n + Math.max(1, Math.ceil((t.length * per) / width)), 0);
const PANEL_LINES = (D) => D.printed.reduce((n, l) => n + lines(l.text, 808, 7.4), 0);

export const layout = (D) => {
  const shapes = [], add = (id, x, y, w, h) => shapes.push({ id, x, y, w, h });
  const C = {};
  const card = (id, x, y, w) => {
    const c = { ...D.cards[id], id, x, y, w };
    c.h = 12 + lines(c.name, w - 16, 8.2) * 18 + 4 + lines(c.line, w - 16, c.mono ? 7.1 : 7.8) * 16 + (c.badge ? 28 : 8);
    C[id] = c; add(`card-${id}`, x, y, w, c.h);
  };
  card('workflow', 16, ROW1, AW); card('job', FW - 16 - CW, ROW1, CW); card('tag', RX + 16, ROW1, RW - 32);
  const row2 = ROW1 + Math.max(C.workflow.h, C.job.h, C.tag.h) + 56;
  card('bad', RX + 16, row2, RW - 32); card('fix', 16, row2, FW - 32);
  const rowH = Math.max(C.bad.h, C.fix.h); C.bad.h = C.fix.h = rowH;
  shapes.filter((s) => s.id === 'card-bad' || s.id === 'card-fix').forEach((s) => { s.h = rowH; });
  const frameH = row2 + rowH + 24, ya = C.workflow.y + 26;
  const dx = [C.workflow.x + AW + 50, C.workflow.x + AW + 126];
  const diamonds = D.diamonds.map((d, i) => ({ ...d, x: dx[i], y: ya }));
  diamonds.forEach((d) => { add(`${d.id}-exit`, d.x - 24, d.y - 30, 48, 14); add(`${d.id}-name`, d.x - Math.ceil(d.label.length * 3.2), d.y + 14, Math.ceil(d.label.length * 6.4), 14); add(`${d.id}-diamond`, d.x - 5, d.y - 5, 10, 10); });
  const labels = [['tag-bad', C.tag.x + (RW - 32) / 2 + 10, (C.tag.y + C.tag.h + row2) / 2 - 7], ['workflow-fix', C.workflow.x + AW / 2 + 10, (C.workflow.y + C.workflow.h + row2) / 2 - 7]]
    .map(([k, x, y]) => { const w = Math.ceil(D.arrows[k].length * 6 + 2); const lx = x; add(`label-${k}`, lx, y, w, 14); return { text: D.arrows[k], x: lx, y, w }; });
  const base = frameH + 20, panelTop = base + 140, panelH = PANEL_LINES(D) * 19 + 28;
  const limitTop = panelTop + panelH + 18, sourceTop = limitTop + 48, footTop = sourceTop + 42, total = footTop + 34;
  return { shapes, C, diamonds, labels, frameH, ya, base, panelTop, panelH, limitTop, sourceTop, footTop, total, height: total + 78 };
};

// Shapes closer than GAP.
export const crowded = (L) => {
  const bad = [], near = (a, b) => a.x < b.x + b.w + GAP && b.x < a.x + a.w + GAP && a.y < b.y + b.h + GAP && b.y < a.y + a.h + GAP;
  L.shapes.forEach((a, i) => L.shapes.slice(i + 1).forEach((b) => { if (!(a.id.split('-')[0] === b.id.split('-')[0] && /-(exit|name|diamond)$/.test(a.id) && /-(exit|name|diamond)$/.test(b.id)) && near(a, b)) bad.push([a.id, b.id]); }));
  return bad;
};

export const where = (page, D, palette = DEFAULT_PALETTE) => {
  const L = layout(D), bad = crowded(L);
  if (bad.length) throw new Error(`figure shapes too close: ${JSON.stringify(bad)}`);
  const { ink: INK, soft: SOFT, line: LINE, paper: PAPER, accent: ACCENT, grey: GREY, chip: CHIP } = palette;
  const FILL = { workflow: '#EFE9F9', job: '#DCEAF9', tag: '#E9E4F3', bad: '#F6E2EC', fix: '#DDF0EE' };
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const abs = (x, y, w, h, css, inner, fit = false) => `<div${fit ? ' data-fit' : ''} style="position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;${css}">${inner}</div>`;
  const diamond = (x, y, acts, s = 10) => abs(x - s / 2, y - s / 2, s, s, `transform:rotate(45deg);box-sizing:border-box;border:2px solid ${acts ? ACCENT : GREY};background:${acts ? ACCENT : PAPER}`, '');
  const frame = (x, w, h, title) => abs(x, 0, w, h, `border:2px dashed ${LINE};border-radius:18px;box-sizing:border-box`, `<div style="position:absolute;left:16px;top:-13px;padding:0 8px;background:${PAPER};font-size:14px;font-weight:700;color:${INK};white-space:nowrap">${esc(title)}</div>`);
  const ghost = (id) => id === 'job' || id === 'tag' || id === 'bad';
  const card = (c) => abs(c.x, c.y, c.w, c.h, `box-sizing:border-box;background:${FILL[c.id]};border:1.5px ${ghost(c.id) ? 'dashed' : 'solid'} ${LINE};border-radius:12px;padding:10px 8px;${ghost(c.id) ? 'opacity:.8' : ''}`,
    `<div style="font-size:14px;font-weight:700;line-height:18px;color:${INK}">${esc(c.name)}</div><div class="${c.mono ? 'mono' : ''}" style="font-size:${c.mono ? 11.5 : 12.5}px;line-height:16px;color:${SOFT};margin-top:4px;white-space:pre-line">${esc(c.line)}</div>`
    + (c.badge ? abs(4, c.h - 28, c.w - 8, 20, `box-sizing:border-box;display:flex;align-items:center;gap:4px;padding:0 5px;border-radius:999px;background:${CHIP};font-size:12px;font-weight:600;color:${ACCENT}`, `<span style="position:relative;flex:none;width:10px;height:10px">${diamond(5, 5, true)}</span><span>${esc(c.badge)}</span>`) : ''), true);
  const { C, ya } = L, [d1, d2] = L.diamonds;
  const head = (id, c) => `<marker id="${id}" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M1 1 L9 5 L1 9" fill="none" stroke="${c}" stroke-width="1.7"/></marker>`;
  const seg = (d, stroke, dash, marker) => `<path d="${d}" fill="none" stroke="${stroke}" stroke-width="${stroke === ACCENT ? 2.6 : 1.8}"${dash ? ' stroke-dasharray="6 5"' : ''}${marker ? ` marker-end="url(#${marker})"` : ''}/>`;
  const mid = (c) => c.x + c.w / 2, bt = (c) => c.y + c.h;
  const paths = [seg(`M${C.workflow.x + AW} ${ya} H${d1.x - 7}`, ACCENT, false), `<path d="M${d1.x - 7} ${ya - 9} V${ya + 9}" stroke="${ACCENT}" stroke-width="3"/>`,
    seg(`M${d1.x + 7} ${ya} H${C.job.x}`, LINE, true, 'g'), seg(`M${C.job.x + CW} ${ya} H${C.tag.x}`, LINE, true, 'g'),
    seg(`M${mid(C.tag)} ${bt(C.tag)} V${C.bad.y}`, LINE, true, 'g'), seg(`M${mid(C.workflow)} ${bt(C.workflow)} V${C.fix.y}`, LINE, false, 'g')].join('');
  const dmarks = L.diamonds.map((d) => diamond(d.x, d.y, true) + abs(d.x - 24, d.y - 30, 48, 14, `font-size:12px;font-weight:700;color:${ACCENT};text-align:center;white-space:nowrap`, esc(D.exit))
    + abs(d.x - Math.ceil(d.label.length * 3.2), d.y + 14, Math.ceil(d.label.length * 6.4), 14, `font-size:12px;font-weight:600;color:${SOFT};white-space:nowrap`, esc(d.label))).join('');
  const labels = L.labels.map((l) => abs(l.x, l.y, l.w, 14, `font-size:12px;line-height:14px;font-weight:600;color:${SOFT};white-space:nowrap`, esc(l.text))).join('');
  const key = (inner, text, y) => `<div style="position:absolute;left:0;top:${y}px;font-size:13px;font-weight:600;color:${SOFT};display:flex;align-items:center;gap:12px"><span style="position:relative;width:28px;height:14px;display:inline-block">${inner}</span>${esc(text)}</div>`;
  const line = (stroke, dash) => `<svg width="28" height="14" style="position:absolute;left:0;top:0"><path d="M0 7 H28" stroke="${stroke}" stroke-width="${dash ? 1.8 : 2.6}"${dash ? ' stroke-dasharray="6 5"' : ''}/></svg>`;
  const rows = D.printed.map((l) => `<div style="color:${l.kind === 'cmd' ? SOFT : INK};white-space:normal;word-break:break-word;font-weight:${l.text.startsWith('exit 1') ? 600 : 400}">${l.kind === 'out' && l.text.startsWith('exit 1') ? `<span style="color:${ACCENT}">exit 1</span>${esc(l.text.slice(6))}` : esc(l.text)}</div>`).join('');
  return page(`<div class="frame" style="width:880px;padding:20px;background:${PAPER};color:${INK};position:relative;height:${L.height}px">
<div style="position:absolute;left:20px;top:20px;width:840px;font-size:20px;line-height:1.35;font-weight:600">${esc(D.title)}</div>
<div style="position:absolute;left:20px;top:78px;width:840px;height:${L.total}px">
${frame(0, FW, L.frameH, D.frames[0])}${frame(RX, RW, L.frameH, D.frames[1])}
<svg width="840" height="${L.frameH}" style="position:absolute;left:0;top:0" xmlns="http://www.w3.org/2000/svg"><defs>${head('g', LINE)}</defs>${paths}</svg>
${Object.values(C).map(card).join('')}${dmarks}${labels}
${key(line(ACCENT, false), D.key.path, L.base)}${key(line(LINE, true), D.key.stopped, L.base + 28)}${key(`<span style="position:absolute;left:7px;top:0">${diamond(7, 7, true, 12)}</span>`, D.key.acts, L.base + 56)}
<div class="eyebrow" style="position:absolute;left:0;top:${L.base + 100}px;font-size:14px;color:${ACCENT}">${esc(D.printed_title)}</div>
${abs(0, L.panelTop, 840, L.panelH, `box-sizing:border-box;border:1.5px solid ${LINE};border-radius:12px;background:${CHIP};padding:14px 16px;font-size:12px;line-height:19px`, rows.replace(/<div style="/g, '<div class="mono" style="'), true)}
${abs(0, L.limitTop, 840, 44, `font-size:13.5px;line-height:20px;color:${INK}`, esc(D.limit), true)}
${abs(0, L.sourceTop, 840, 36, `font-size:12.5px;line-height:18px;color:${SOFT}`, esc(D.source), true)}
<div style="position:absolute;left:0;top:${L.footTop}px;font-size:16px;color:${SOFT}">${esc(D.footer)}</div>
</div></div>`);
};

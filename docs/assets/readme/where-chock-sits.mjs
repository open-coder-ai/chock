// The README "How it works" figure. Takes the page wrapper and where-chock-sits.json; every word comes from the data, only positions live here.
export const where = (page, W) => {
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const INK = '#2B2A35', SOFT = '#5C5A6B', LINE = '#6B6877', PAPER = '#FBF7EE', ACCENT = '#C2410C';
  const abs = (x, y, w, h, css, inner) => `<div style="position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;${css}">${inner}</div>`;
  const frame = (x, w, h, title) => abs(x, 0, w, h, `border:2px dashed ${LINE};border-radius:18px`, `<div style="position:absolute;left:10px;top:-13px;padding:0 8px;white-space:nowrap;background:${PAPER};font-size:14px;font-weight:600;color:${INK}">${esc(title)}</div>`);
  const box = (x, y, w, h, fill, name, line = '') => abs(x, y, w, h, `background:${fill};border:1.5px solid ${LINE};border-radius:12px;padding:6px 8px;display:flex;flex-direction:column;justify-content:center;gap:2px`, `<span style="font-size:16px;font-weight:700;color:${INK}">${esc(name)}</span>${line ? `<span style="font-size:14px;line-height:1.3;color:${SOFT}">${esc(line)}</span>` : ''}`);
  const small = (x, y, text, css = '') => `<span style="position:absolute;left:${x}px;top:${y}px;font-size:13px;font-weight:600;color:${SOFT};white-space:nowrap;${css}">${esc(text)}</span>`;
  const pill = (cx, cy, p) => `<span style="position:absolute;left:${cx}px;top:${cy}px;transform:translate(-50%,-50%);white-space:nowrap;padding:2px 9px;border-radius:999px;font-size:13px;font-weight:700;border:2px solid ${ACCENT};${p.kind === 'all' ? `background:${ACCENT};color:#fff` : `background:${PAPER};color:${ACCENT}`}">${esc(p.label)}</span>`;
  const sample = (kind) => pill(0, 0, { kind, label: '' }).replace('position:absolute;left:0px;top:0px;transform:translate(-50%,-50%);', 'display:inline-block;vertical-align:middle;width:26px;height:12px;padding:0;');
  const path = (d, color = LINE, w = 1.8) => `<path d="${d}" fill="none" stroke="${color}" stroke-width="${w}"${color === LINE ? ' marker-end="url(#g)"' : ''}/>`;
  const A = W.agent, P = Object.fromEntries(W.points.map((p) => [p.id, p]));
  const MARKERS = { 'session-start': [108, 200], 'ambient-rule': [246, 67], stop: [268, 22], 'pre-tool-use': [335, 185], 'post-tool-use': [402, 150], 'mcp-gateway': [350, 329], 'git-commit': [648, 110], 'git-push': [648, 162], 'ci-gate': [648, 266] };
  // Thin accent lines from each marker to the Chock box; the three vertical trunks are shared.
  const TRUNKS = ['M108 211 V470', 'M268 22 V470', 'M433 150 V470', 'M630 110 V470'];
  const SPURS = ['M246 67 H268', 'M268 185 H335', 'M402 150 H433', 'M350 329 H433', 'M630 110 H648', 'M630 162 H648', 'M630 266 H648'];
  const lines = `<svg width="840" height="500" style="position:absolute;left:0;top:0" xmlns="http://www.w3.org/2000/svg"><defs>
<marker id="g" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M1 1 L9 5 L1 9" fill="none" stroke="${LINE}" stroke-width="1.6"/></marker></defs>
${['M88 200 H184', 'M246 70 H290', 'M410 66 H456', 'M456 82 H410', 'M355 112 V230', 'M318 174 V112', 'M402 230 V112', 'M350 294 V364', 'M350 40 V22 H48 V40'].map((d) => path(d)).join('')}
${[0, 1, 2, 3, 4].map((i) => path(`M730 ${76 + i * 52} V${92 + i * 52}`)).join('')}
${[...TRUNKS, ...SPURS].map((d) => path(d, ACCENT, 1.6)).join('')}</svg>`;
  const chips = W.stops.map((s) => `<span style="padding:5px 10px;border:1.5px solid ${LINE};border-radius:999px;background:#fff;font-size:13px;font-weight:600;color:${INK};white-space:nowrap">${esc(s)}</span>`).join('');
  return page(`<div class="frame" style="width:880px;padding:20px;background:${PAPER};color:${INK};position:relative;height:772px">
<div style="position:absolute;left:20px;top:20px;width:840px;font-size:20px;line-height:1.35;font-weight:600">${esc(W.title)}</div>
<div style="position:absolute;left:20px;top:72px;width:840px;height:690px">
${frame(0, 96, 424, W.you.name)}${box(8, 40, 80, 190, '#EFE9F9', W.you.box)}
${frame(120, 460, 424, A.name)}
${box(136, 40, 110, 54, '#DDEFE0', A.context.name)}${box(290, 40, 120, 70, '#DCEAF9', A.loop.name)}${box(456, 60, 110, 44, '#E8E1F6', A.model.name)}
${box(290, 230, 120, 64, '#ECE6D8', A.tools.name, A.tools.line)}${box(290, 364, 120, 40, '#E9E4F3', A.mcp.name)}
${frame(604, 236, 424, W.repo.name)}${W.repo.items.map((t, i) => abs(660, 40 + i * 52, 140, 36, `background:#DDF0EE;border:1.5px solid ${LINE};border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:600;color:${INK}`, esc(t))).join('')}
${abs(90, 470, 750, 56, `background:#FFF1E8;border:2.5px solid ${ACCENT};border-radius:14px;padding:6px 16px;display:flex;flex-direction:column;justify-content:center`, `<span style="font-size:19px;font-weight:700;color:${ACCENT}">${esc(W.chock.name)}</span><span style="font-size:15px;color:${INK}">${esc(W.chock.line)}</span>`)}
${lines}
${small(276, 128, A.arrows.block, 'width:38px;text-align:right')}${small(362, 202, A.arrows.allow)}
${W.points.map((p) => pill(...MARKERS[p.id], p)).join('')}
<div style="position:absolute;left:0;top:550px;width:840px;display:flex;justify-content:space-between;align-items:center"><span class="eyebrow" style="font-size:14px;color:${ACCENT}">${esc(W.stops_title)}</span><span style="font-size:13px;font-weight:600;color:${SOFT}">${sample('all')} ${esc(W.key.all)} &nbsp;&nbsp; ${sample('hooks')} ${esc(W.key.hooks)}</span></div>
<div style="position:absolute;left:0;top:582px;width:840px;display:flex;flex-wrap:wrap;gap:8px">${chips}</div>
<div style="position:absolute;left:0;top:650px;font-size:16px;color:${SOFT}">${esc(W.footer)}</div>
</div></div>`);
};

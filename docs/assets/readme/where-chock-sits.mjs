// The README "How it works" figure. Takes the page wrapper and where-chock-sits.json; every word comes from the data, only positions live here.
export const where = (page, W) => {
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const INK = '#2B2A35', SOFT = '#5C5A6B', LINE = '#6B6877', PAPER = '#FBF7EE', ACCENT = '#C2410C';
  const abs = (x, y, w, h, css, inner) => `<div style="position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;${css}">${inner}</div>`;
  const frame = (x, w, h, title, sub) => abs(x, 0, w, h, `border:2px dashed ${LINE};border-radius:18px`, `<div style="position:absolute;left:10px;top:-13px;padding:0 8px;white-space:nowrap;background:${PAPER};font-size:14px;font-weight:600;color:${INK}">${esc(title)}${sub && sub.title ? ` <span style="font-weight:500;color:${SOFT}">&middot; ${esc(sub.text)}</span>` : ''}</div>${sub && !sub.title ? `<div style="position:absolute;left:34px;bottom:10px;font-size:13px;font-weight:600;color:${SOFT};white-space:nowrap">${esc(sub.text)}</div>` : ''}`);
  const box = (x, y, w, h, fill, name, line = '') => abs(x, y, w, h, `background:${fill};border:1.5px solid ${LINE};border-radius:12px;padding:6px 8px;display:flex;flex-direction:column;justify-content:center;gap:2px`, `<span style="font-size:16px;font-weight:700;color:${INK}">${esc(name)}</span>${line ? `<span style="font-size:14px;line-height:1.3;color:${SOFT}">${esc(line)}</span>` : ''}`);
  const small = (x, y, text, css = '') => `<span style="position:absolute;left:${x}px;top:${y}px;font-size:13px;font-weight:600;color:${SOFT};white-space:nowrap;${css}">${esc(text)}</span>`;
  const WRAP = new Set(['instructions_loaded', 'subagent_start', 'subagent_stop']);
  const pill = (p, cx, cy) => `<span style="position:absolute;left:${cx}px;top:${cy}px;transform:translate(-50%,-50%);${WRAP.has(p.id) ? 'white-space:normal;box-sizing:border-box;width:88px;text-align:center;line-height:1.1;' : 'white-space:nowrap;'}padding:2px 9px;border-radius:${WRAP.has(p.id) ? 14 : 999}px;font-size:13px;font-weight:700;${p.acts ? `border:2px solid ${ACCENT};background:${ACCENT};color:#fff` : `border:1.5px solid #9A97A6;background:${PAPER};color:#7C7989`}">${esc(p.label)}</span>`;
  const path = (d, color = LINE, w = 1.8, head = color === LINE) => `<path d="${d}" fill="none" stroke="${color}" stroke-width="${w}"${head ? ' marker-end="url(#g)"' : ''}/>`;
  const A = W.agent, P = Object.fromEntries(W.points.map((p) => [p.id, p]));
  // Marker positions (on the arrow or box where the point happens) and the trunks joining acting markers to the Chock box.
  const AT = { session_start: [108, 330], session_end: [108, 80], prompt_submit: [215, 195], instructions_loaded: [258, 142], pre_compact: [176, 120], pre_tool: [333, 285], post_tool: [395, 250], tool_failure: [255, 262], file_changed: [500, 352], subagent_start: [445, 135], subagent_stop: [445, 205], stop: [300, 20], 'ambient-rule': [150, 164], 'mcp-gateway': [350, 407], 'git-commit': [648, 110], 'git-push': [648, 162], 'ci-gate': [648, 266] };
  const TRUNKS = ['M108 341 V540', 'M150 164 V540', 'M255 262 V540', 'M598 20 V540', 'M630 110 V540'];
  const SPURS = ['M300 20 H598', 'M395 250 H598', 'M400 407 H598', 'M306 285 H255', 'M630 162 H648', 'M630 266 H648'];
  const ARROWS = ['M120 80 H88', 'M88 330 H120', 'M88 195 H300', 'M216 142 H300', 'M365 120 V80', 'M415 80 V120', 'M400 135 H486', 'M486 205 H400', 'M350 222 V320', 'M318 274 V222', 'M395 320 V222', 'M300 352 H255 V210 H300', 'M350 384 V430', 'M400 352 H586 V58 H660', 'M320 120 V20 H48 V40'];
  const chain = W.repo.items.slice(1).map((_, i) => path(`M730 ${76 + i * 52} V${92 + i * 52}`)).join('');
  const lines = `<svg width="840" height="600" style="position:absolute;left:0;top:0" xmlns="http://www.w3.org/2000/svg"><defs>
<marker id="g" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M1 1 L9 5 L1 9" fill="none" stroke="${LINE}" stroke-width="1.6"/></marker></defs>
${ARROWS.map((d) => path(d)).join('')}${chain}${[...TRUNKS, ...SPURS].map((d) => path(d, ACCENT, 1.6, false)).join('')}</svg>`;
  const chips = W.stops.map((s) => `<span style="padding:5px 10px;border:1.5px solid ${LINE};border-radius:999px;background:#fff;font-size:13px;font-weight:600;color:${INK};white-space:nowrap">${esc(s)}</span>`).join('');
  const sample = (acts) => `<span style="display:inline-block;vertical-align:middle;width:26px;height:12px;border-radius:999px;${acts ? `background:${ACCENT};border:2px solid ${ACCENT}` : 'border:1.5px solid #9A97A6'}"></span>`;
  return page(`<div class="frame" style="width:880px;padding:20px;background:${PAPER};color:${INK};position:relative;height:840px">
<div style="position:absolute;left:20px;top:20px;width:840px;font-size:20px;line-height:1.35;font-weight:600">${esc(W.title)}</div>
<div style="position:absolute;left:20px;top:72px;width:840px;height:760px">
${frame(0, 96, 500, W.you.name, null)}${box(8, 40, 80, 420, '#EFE9F9', W.you.box)}
${frame(120, 460, 500, A.name, { title: true, text: A.sub })}
${box(136, 120, 80, 48, '#DDEFE0', A.context.name)}${box(300, 120, 100, 100, '#DCEAF9', A.loop.name)}${box(340, 36, 100, 44, '#E8E1F6', A.model.name)}
${box(300, 320, 100, 64, '#ECE6D8', A.tools.name, A.tools.line)}${box(300, 430, 100, 40, '#E9E4F3', A.mcp.name)}${box(486, 120, 90, 110, '#F6E2EC', A.subagents.name)}
${frame(604, 236, 500, W.repo.name, { title: false, text: W.repo.sub })}${W.repo.items.map((t, i) => abs(660, 40 + i * 52, 140, 36, `background:#DDF0EE;border:1.5px solid ${LINE};border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:600;color:${INK}`, esc(t))).join('')}
${abs(90, 540, 750, 56, `background:#FFF1E8;border:2.5px solid ${ACCENT};border-radius:14px;padding:6px 16px;display:flex;flex-direction:column;justify-content:center`, `<span style="font-size:19px;font-weight:700;color:${ACCENT}">${esc(W.chock.name)}</span><span style="font-size:15px;color:${INK}">${esc(W.chock.line)}</span>`)}
${lines}
${small(276, 232, A.arrows.block, 'width:38px;text-align:right')}${small(356, 300, A.arrows.allow)}
${W.points.map((p) => pill(p, ...AT[p.id])).join('')}
<div style="position:absolute;left:0;top:620px;width:840px;display:flex;justify-content:space-between;align-items:center"><span class="eyebrow" style="font-size:14px;color:${ACCENT}">${esc(W.stops_title)}</span><span style="font-size:13px;font-weight:600;color:${SOFT}">${sample(true)} ${esc(W.key.acts)} &nbsp;&nbsp; ${sample(false)} ${esc(W.key.exposed)}</span></div>
<div style="position:absolute;left:0;top:652px;width:840px;display:flex;flex-wrap:wrap;gap:8px">${chips}</div>
<div style="position:absolute;left:0;top:710px;font-size:16px;color:${SOFT}">${esc(W.footer)}</div>
</div></div>`);
};

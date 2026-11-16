// The README "How it works" figure. Takes the page wrapper and where-chock-sits.json; every word comes from the data, only positions live here.
export const where = (page, W) => {
  const wEsc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const INK = '#2B2A35', SOFT = '#5C5A6B', LINE = '#6B6877', PAPER = '#FBF7EE', ACCENT = '#C2410C';
  const wAbs = (x, y, w, h, css, inner) => `<div style="position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;${css}">${inner}</div>`;
  const wFrame = (x, y, w, h, title, sub) => wAbs(x, y, w, h, `border:2px dashed ${LINE};border-radius:18px`, `<div style="position:absolute;left:10px;top:-13px;padding:0 8px;white-space:nowrap;background:${PAPER};font-size:14px;font-weight:600;color:${INK}">${wEsc(title)}${sub ? ` <span style="font-weight:500;color:${SOFT}">&middot; ${wEsc(sub)}</span>` : ''}</div>`);
  const wBox = (x, y, w, h, fill, b) => wAbs(x, y, w, h, `background:${fill};border:1.5px solid ${LINE};border-radius:12px;padding:8px 12px;display:flex;flex-direction:column;justify-content:center;gap:3px`, `<span style="font-size:16px;font-weight:700;color:${INK}">${wEsc(b.name || b.box)}</span><span style="font-size:14px;line-height:1.35;color:${SOFT}">${wEsc(b.line)}</span>`);
  const wPlain = (x, y, w, h, fill, text) => wAbs(x, y, w, h, `background:${fill};border:1.5px solid ${LINE};border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:600;color:${INK}`, wEsc(text));
  const wTag = (x, y, text, extra = '') => `<span style="position:absolute;left:${x}px;top:${y}px;font-size:13px;font-weight:600;color:${SOFT};${extra}">${wEsc(text)}</span>`;
  const wDot = (x, y, n) => wAbs(x - 12, y - 12, 24, 24, `border-radius:50%;background:${ACCENT};color:#fff;font-size:14px;font-weight:700;display:flex;align-items:center;justify-content:center`, n);
  const AG = W.agent;
  // Where each point attaches: connector path from the top of the Chock box, and where its number sits.
  const GEO = {
    'session-start': { d: 'M200 460 V410', dot: [200, 438] },
    'ambient-rule': { d: 'M140 460 V84 H150', dot: [140, 438] },
    stop: { d: 'M345 460 V200 H395', dot: [345, 438] },
    'pre-tool-use': { d: 'M380 460 V270 H395', dot: [380, 416] },
    'mcp-gateway': { d: 'M280 460 V388', dot: [280, 438] },
    'post-tool-use': { d: 'M470 460 V388', dot: [470, 438] },
    'git-commit': { d: 'M624 460 V118 H655', dot: [624, 438] },
    'git-push': { d: 'M642 460 V176 H655', dot: [642, 416] },
    'ci-gate': { d: 'M826 460 V292 H805', dot: [826, 438] },
  };
  const wLine = (d, color = LINE, w = 1.8) => `<path d="${d}" fill="none" stroke="${color}" stroke-width="${w}" marker-end="url(#a${color === ACCENT ? 'c' : 'g'})"/>`;
  const wArrows = `<svg width="840" height="560" style="position:absolute;left:0;top:0" xmlns="http://www.w3.org/2000/svg"><defs>
  <marker id="ag" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M1 1 L9 5 L1 9" fill="none" stroke="${LINE}" stroke-width="1.6"/></marker>
  <marker id="ac" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M1 1 L9 5 L1 9" fill="none" stroke="${ACCENT}" stroke-width="1.8"/></marker></defs>
  ${wLine('M100 105 H130')}${wLine('M330 84 H395')}${wLine('M330 150 H395')}${wLine('M395 168 H330')}
  ${wLine('M480 210 V240')}${wLine('M480 300 V326')}${wLine('M565 357 H584 V125 H565')}${wLine('M395 357 H330')}
  ${W.points.map((p) => wLine(GEO[p.id].d, ACCENT, 2.2)).join('')}
  ${W.repo.items.slice(1).map((_, i) => wLine(`M730 ${80 + i * 58} V${98 + i * 58}`)).join('')}</svg>`;
  const wStrip = W.stops.map((s, i) => wAbs(i * 170, 0, 160, 160, `background:#fff;border:1.5px solid ${LINE};border-radius:12px;padding:10px 12px;display:flex;flex-direction:column;justify-content:space-between`, `<span style="font-size:14px;line-height:1.4;color:${INK}">${wEsc(s.line)}</span><span class="mono" style="font-size:13px;font-weight:600;align-self:flex-start;padding:2px 8px;border-radius:6px;background:${s.tier === 'commit' ? '#FCE3D3' : '#E3ECF8'};color:${INK}">${s.tier === 'commit' ? 'at commit' : 'in the agent, best-effort'}</span>`)).join('');
  const wLegend = W.points.map((c, i) => wAbs((i % 3) * 285, Math.floor(i / 3) * 128, 270, 118, `border-top:2.5px solid ${ACCENT};padding-top:8px`, `<div style="font-size:15px;font-weight:700;color:${INK}"><span style="color:${ACCENT}">${c.n}</span> ${wEsc(c.name)}</div><div style="font-size:14px;line-height:1.4;color:${SOFT};margin-top:3px">${wEsc(c.line)} <b style="color:${INK}">${wEsc(c.scope[0].toUpperCase() + c.scope.slice(1))}.</b></div>`)).join('');
  return page(`<div class="frame" style="width:880px;padding:20px;background:${PAPER};color:${INK};position:relative;height:1330px">
  <div style="position:absolute;left:20px;top:20px;width:840px;font-size:20px;line-height:1.35;font-weight:600">${wEsc(W.title)}</div>
  <div style="position:absolute;left:20px;top:90px;width:840px;height:1200px">
  ${wFrame(0, 0, 110, 410, W.you.name)}${wBox(10, 40, 90, 130, '#EFE9F9', { name: W.you.box, line: W.you.line })}
  ${wFrame(130, 0, 470, 410, AG.name, AG.sub)}
  ${wBox(150, 40, 180, 88, '#DDEFE0', AG.context)}${wBox(150, 145, 180, 72, '#E8E1F6', AG.model)}${wBox(395, 40, 170, 170, '#DCEAF9', AG.loop)}
  ${wBox(395, 240, 170, 60, '#F6E2EC', AG.hook)}${wBox(395, 326, 170, 62, '#ECE6D8', AG.tools)}${wBox(150, 326, 180, 62, '#E9E4F3', AG.mcp)}
  ${wFrame(604, 0, 236, 410, W.repo.name)}${W.repo.items.map((t, i) => wPlain(655, 40 + i * 58, 150, 40, '#DDF0EE', t)).join('')}
  ${wAbs(130, 460, 710, 80, `background:#FFF1E8;border:2.5px solid ${ACCENT};border-radius:14px;padding:10px 16px;display:flex;flex-direction:column;justify-content:center;gap:3px`, `<span style="font-size:20px;font-weight:700;color:${ACCENT}">${wEsc(W.chock.name)}</span><span style="font-size:15px;color:${INK}">${wEsc(W.chock.line)}</span>`)}
  ${wArrows}
  ${wTag(333, 64, AG.arrows.feeds, 'width:60px;text-align:center')}${wTag(331, 128, AG.arrows.plan, 'width:64px;text-align:center')}
  ${wTag(392, 216, AG.arrows.call, 'width:74px;text-align:right')}<span style="position:absolute;left:566px;top:200px;writing-mode:vertical-rl;font-size:13px;font-weight:600;color:${SOFT}">${wEsc(AG.arrows.result)}</span>${wTag(346, 334, AG.arrows.calls)}
  ${W.points.map((p) => wDot(...GEO[p.id].dot, p.n)).join('')}
  ${wAbs(0, 568, 840, 390, '', wLegend)}
  ${wAbs(0, 976, 840, 24, '', `<span class="eyebrow" style="font-size:14px;color:${ACCENT}">${wEsc(W.stops_title)}</span>`)}
  ${wAbs(0, 1008, 840, 160, '', wStrip)}
  ${wAbs(0, 1190, 840, 30, '', `<span style="font-size:16px;color:${SOFT}">${wEsc(W.footer)}</span>`)}
  </div></div>`);
};

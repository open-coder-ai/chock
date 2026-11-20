// The README "where can each agent be stopped" picture: one card per agent in dashed group boxes, one diamond chip per place a check can run. Every word and count comes from agents.json (agents_data.py); positions are computed here, and `layout` reports every shape so a test can check nothing overlaps.
import { DEFAULT_PALETTE } from './where-chock-sits.mjs';

const BW = 840, BP = 10, CG = 8, PER = 6.6, CHIP_H = 20, CHIP_G = 4, COLS = 2;
const CW = (BW - 2 * BP - (COLS - 1) * CG) / COLS;
const chipW = (text) => Math.ceil(text.length * PER + 30);

// The chips of one agent, strongest first: those its row has, the hook labelled with its grade.
export const chipsOf = (W, r) => W.columns.filter((c) => r[c.id]).map((c) => ({ c, text: c.id === 'hook' ? `${c.label}: ${r.hook}` : c.label }));

export const layout = (W) => {
  const shapes = [], boxes = [], cards = [], chips = [];
  const add = (id, x, y, w, h) => shapes.push({ id, x, y, w, h });
  let y = 12;
  [...new Set(W.rows.map((r) => r.plugin))].forEach((kind, bi) => {
    const rows = W.rows.filter((r) => r.plugin === kind), top = y;
    let cy = y + 30;
    for (let i = 0; i < rows.length; i += COLS) {
      const slice = rows.slice(i, i + COLS).map((r, j) => {
        const card = { r, x: BP + j * (CW + CG), y: cy, w: CW, chips: [] };
        let cx = 10, cr = 0;
        chipsOf(W, r).forEach((k) => {
          const w = chipW(k.text);
          if (cx + w > CW - 10 && cx > 10) { cx = 10; cr += 1; }
          card.chips.push({ ...k, x: card.x + cx, y: cy + 36 + cr * (CHIP_H + CHIP_G), w, h: CHIP_H });
          cx += w + CHIP_G;
        });
        card.rows = cr + 1;
        return card;
      });
      const h = 36 + Math.max(...slice.map((c) => c.rows)) * (CHIP_H + CHIP_G) + 6;
      slice.forEach((c) => { c.h = h; cards.push(c); chips.push(...c.chips); add(`card-${c.r.id}`, c.x, c.y, c.w, c.h); });
      cy += h + CG;
    }
    const h = cy - CG + BP - top;
    boxes.push({ kind, x: 0, y: top, w: BW, h, label: W.groups[kind] });
    add(`box-${bi}`, 0, top, BW, h);
    y = top + h + 30;
  });
  const legendTop = y;
  return { shapes, boxes, cards, chips, legendTop, Ht: legendTop + 26 * W.legend.length + 36 };
};

// Cards closer than their gap, chips off their card or on each other, names too long for a card.
export const crowded = (L) => {
  const bad = [], near = (a, b, g = 2) => a.x < b.x + b.w + g && b.x < a.x + a.w + g && a.y < b.y + b.h + g && b.y < a.y + a.h + g;
  L.shapes.filter((s) => s.id.startsWith('card-')).forEach((a, i, all) => all.slice(i + 1).forEach((b) => { if (near(a, b)) bad.push([a.id, b.id]); }));
  L.cards.forEach((c) => {
    if (c.r.name.length * 8.2 + 20 > c.w) bad.push([c.r.id, 'name-text']);
    c.chips.forEach((k, i) => {
      if (k.x + k.w > c.x + c.w - 8 || k.y + k.h > c.y + c.h - 2) bad.push([c.r.id, k.text, 'off-card']);
      c.chips.slice(i + 1).forEach((o) => { if (near(k, o, 1)) bad.push([c.r.id, k.text, o.text]); });
    });
  });
  L.boxes.forEach((b, i) => L.boxes.slice(i + 1).forEach((o) => { if (near(b, o, 12)) bad.push(['box', b.kind, o.kind]); }));
  return bad;
};

export const where = (page, W, palette = DEFAULT_PALETTE) => {
  const L = layout(W), bad = crowded(L);
  if (bad.length) throw new Error(`figure shapes too close: ${JSON.stringify(bad)}`);
  const { ink: INK, soft: SOFT, line: LINE, paper: PAPER, accent: ACCENT, grey: GREY, chip: CHIP, hollow: HOLLOW, fill: FILL } = palette;
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const abs = (x, y, w, h, css, inner) => `<div style="position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;${css}">${inner}</div>`;
  const diamond = (hard, s = 10) => `<span style="position:relative;flex:none;width:10px;height:10px;display:inline-block"><span style="position:absolute;left:${5 - s / 2}px;top:${5 - s / 2}px;width:${s}px;height:${s}px;transform:rotate(45deg);box-sizing:border-box;border:2px solid ${hard ? ACCENT : GREY};background:${hard ? ACCENT : PAPER}"></span></span>`;
  const tones = [FILL.context, FILL.subagents, FILL.tools], kinds = [...new Set(W.rows.map((r) => r.plugin))];
  const fill = Object.fromEntries(kinds.map((k, i) => [k, tones[i]]));
  const boxes = L.boxes.map((b) => abs(b.x, b.y, b.w, b.h, `border:2px dashed ${LINE};border-radius:18px;box-sizing:border-box`, `<div style="position:absolute;left:16px;top:-13px;padding:0 8px;background:${PAPER};font-size:14px;font-weight:700;color:${INK};white-space:nowrap">${esc(b.label)}</div>`)).join('');
  const cards = L.cards.map((c) => abs(c.x, c.y, c.w, c.h, `box-sizing:border-box;background:${fill[c.r.plugin]};border:1.5px solid ${LINE};border-radius:12px;padding:10px 8px`, `<div style="font-size:14px;font-weight:700;line-height:18px;color:${INK}">${esc(c.r.name)}</div>`)).join('');
  const chip = (k) => abs(k.x, k.y, k.w, k.h, `box-sizing:border-box;display:flex;align-items:center;gap:4px;padding:0 6px;border-radius:999px;background:${CHIP};white-space:nowrap;font-size:12px;line-height:14px;font-weight:600;color:${k.c.hard ? ACCENT : HOLLOW}`, `${diamond(k.c.hard)}<span>${esc(k.text)}</span>`);
  const key = W.legend.map((l, i) => abs(0, L.legendTop + i * 26, BW, 20, `font-size:13px;font-weight:600;color:${SOFT};display:flex;align-items:center;gap:12px;white-space:nowrap`, `${l.hard === null ? '<span style="width:10px;display:inline-block"></span>' : diamond(l.hard)}${esc(l.text)}`)).join('');
  return page(`<div class="frame" style="width:880px;padding:20px;background:${PAPER};color:${INK};position:relative;height:${L.Ht + 110}px">
<div style="position:absolute;left:20px;top:20px;width:840px;font-size:20px;line-height:1.35;font-weight:600">${esc(W.title)}</div>
<div style="position:absolute;left:20px;top:78px;width:840px;height:${L.Ht}px">
${boxes}${cards}${L.chips.map(chip).join('')}${key}
<div style="position:absolute;left:0;top:${L.Ht - 26}px;font-size:16px;color:${SOFT}">${esc(W.footer)}</div>
</div></div>`);
};

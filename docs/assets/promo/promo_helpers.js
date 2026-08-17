'use strict';
const W = 1280, H = 720;
const cv = document.getElementById('c');
const ctx = cv.getContext('2d');

const C = {
  bg:'#1e1e2e', mantle:'#181825', crust:'#11111b', surf:'#313244', ov:'#45475a',
  text:'#cdd6f4', sub:'#a6adc8', dim:'#6c7086',
  green:'#a6e3a1', red:'#f38ba8', blue:'#89b4fa', mauve:'#cba6f7',
  yellow:'#f9e2af', peach:'#fab387', teal:'#94e2d5'
};
const SANS = '"Segoe UI", system-ui, sans-serif';
const MONO = '"Cascadia Code", Consolas, monospace';

// ---------- helpers ----------
const clamp01 = x => x < 0 ? 0 : x > 1 ? 1 : x;
const seg = (t, a, b) => clamp01((t - a) / (b - a));
const ez  = x => { x = clamp01(x); return x * x * (3 - 2 * x); };            // smoothstep
const ezo = x => { x = clamp01(x); return 1 - Math.pow(1 - x, 3); };         // ease-out cubic
const lerp = (a, b, x) => a + (b - a) * x;

function rr(x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function card(x, y, w, h, r, fill, stroke, lw) {
  rr(x, y, w, h, r);
  ctx.fillStyle = fill; ctx.fill();
  if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = lw || 1.5; ctx.stroke(); }
}

function text(s, x, y, font, color, align, alpha) {
  ctx.save();
  ctx.font = font; ctx.fillStyle = color;
  ctx.textAlign = align || 'left'; ctx.textBaseline = 'alphabetic';
  if (alpha !== undefined) ctx.globalAlpha *= clamp01(alpha);
  ctx.fillText(s, x, y);
  ctx.restore();
}

// typed substring by local time
const typed = (s, lt, start, cps) => s.substring(0, Math.max(0, Math.floor((lt - start) * cps)));

// the Chock logo: a wheel + wedge chock, drawn as vectors
function logo(x, y, s, alpha, tile) {
  ctx.save();
  ctx.translate(x, y); ctx.scale(s, s);
  ctx.globalAlpha *= (alpha === undefined ? 1 : clamp01(alpha));
  if (tile) {
    // The brand tile exactly as the README renders it: gold mark on the navy square.
    ctx.beginPath(); ctx.roundRect(-36, -34, 96, 90, 15);
    ctx.fillStyle = '#0D1626'; ctx.fill();
    ctx.strokeStyle = 'rgba(217,180,92,0.35)'; ctx.lineWidth = 1.5; ctx.stroke();
  }
  // Brand mark: the gold wheel-and-wedge from docs/assets/logo.svg (#D9B45C on navy);
  // on the dark video ground the mark renders in its gold, exactly as on the navy tile.
  const GOLD = '#D9B45C';
  // wheel
  ctx.beginPath(); ctx.arc(0, 0, 22, 0, Math.PI * 2);
  ctx.strokeStyle = GOLD; ctx.lineWidth = 5; ctx.stroke();
  ctx.beginPath(); ctx.arc(0, 0, 7, 0, Math.PI * 2);
  ctx.fillStyle = GOLD; ctx.fill();
  // spokes
  ctx.lineWidth = 3;
  for (let i = 0; i < 4; i++) {
    const a = i * Math.PI / 2 + Math.PI / 4;
    ctx.beginPath(); ctx.moveTo(Math.cos(a) * 8, Math.sin(a) * 8);
    ctx.lineTo(Math.cos(a) * 19, Math.sin(a) * 19); ctx.stroke();
  }
  // chock wedge, set against the wheel at 4-5 o'clock
  ctx.beginPath();
  ctx.moveTo(14, 24); ctx.lineTo(38, 24); ctx.lineTo(38, 4); ctx.closePath();
  ctx.fillStyle = GOLD; ctx.fill();
  ctx.restore();
}

// scene chrome: heading + kicker at top
function heading(kicker, title, alpha, lt) {
  const rise = (1 - ezo(seg(lt, 0, 0.8))) * 14;
  ctx.save(); ctx.globalAlpha *= alpha;
  text(kicker.toUpperCase(), 80, 96 + rise, `600 15px ${SANS}`, C.mauve, 'left');
  text(title, 80, 140 + rise, `600 38px ${SANS}`, C.text, 'left');
  ctx.restore();
}

// terminal-style window frame; returns content origin
function windowFrame(x, y, w, h, title, alpha, borderColor) {
  ctx.save(); ctx.globalAlpha *= alpha;
  ctx.shadowColor = 'rgba(0,0,0,0.5)'; ctx.shadowBlur = 30; ctx.shadowOffsetY = 10;
  card(x, y, w, h, 12, C.crust, borderColor || C.ov, borderColor ? 2.5 : 1.5);
  ctx.shadowColor = 'transparent';
  card(x, y, w, 40, 12, C.mantle, null);
  ctx.fillStyle = C.mantle; ctx.fillRect(x, y + 20, w, 20);
  const dots = ['#f38ba8', '#f9e2af', '#a6e3a1'];
  dots.forEach((d, i) => { ctx.beginPath(); ctx.arc(x + 24 + i * 22, y + 20, 6.5, 0, 7); ctx.fillStyle = d; ctx.fill(); });
  text(title, x + w / 2, y + 26, `13px ${MONO}`, C.dim, 'center');
  ctx.restore();
  return { cx: x + 26, cy: y + 66 };
}


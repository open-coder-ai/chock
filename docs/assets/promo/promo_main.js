'use strict';
// ==================================================================
// master timeline
// ==================================================================
const SCENES = [
  { f: scene1, t0: 0,  t1: 12 },
  { f: scene2, t0: 12, t1: 22 },
  { f: scene3, t0: 22, t1: 34 },
  { f: scene4, t0: 34, t1: 48 },
  { f: scene5, t0: 48, t1: 58 },
  { f: scene6, t0: 58, t1: 68 },
  { f: scene7, t0: 68, t1: 75 },
];
const TOTAL = 75;
const XFADE = 0.55;

function draw(t) {
  // background with a very subtle vignette
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = 1;
  ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
  const g = ctx.createRadialGradient(W / 2, H / 2, 200, W / 2, H / 2, 900);
  g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(1, 'rgba(0,0,0,0.35)');
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);

  for (const s of SCENES) {
    if (t < s.t0 - XFADE || t > s.t1 + XFADE) continue;
    const lt = t - s.t0;
    const fadeIn  = s.t0 === 0 ? ez(seg(t, 0, 0.5)) : ez(seg(t, s.t0 - XFADE, s.t0 + XFADE));
    const fadeOut = s.t1 === TOTAL ? 1 - ez(seg(t, TOTAL - 1.2, TOTAL - 0.1))
                                   : 1 - ez(seg(t, s.t1 - XFADE, s.t1 + XFADE));
    const alpha = Math.min(fadeIn, fadeOut);
    if (alpha > 0.002) s.f(Math.max(0, lt), alpha);
  }

  // persistent watermark (not during CTA)
  const wm = 1 - ez(seg(t, 67.5, 68.5));
  if (wm > 0.01) {
    ctx.save(); ctx.globalAlpha = 0.75 * wm;
    logo(W - 148, H - 48, 0.62, 1, true);
    text('Chock', W - 104, H - 42, `600 17px ${SANS}`, C.sub);
    ctx.restore();
  }
  // progress bar
  ctx.fillStyle = 'rgba(203,166,247,0.35)';
  ctx.fillRect(0, H - 4, W * (t / TOTAL), 4);
}

window.seek = t => { draw(t); return true; };
window.TOTAL = TOTAL;
draw(0);

// live preview when opened by hand: press space to play/pause
let playing = false, start = 0;
function loop(ts) {
  if (!playing) return;
  const t = ((ts - start) / 1000) % TOTAL;
  draw(t);
  requestAnimationFrame(loop);
}
document.addEventListener('keydown', e => {
  if (e.code === 'Space') {
    playing = !playing;
    if (playing) { start = performance.now(); requestAnimationFrame(loop); }
  }
});

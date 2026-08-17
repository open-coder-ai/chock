'use strict';
// ==================================================================
// SCENE 1  (0–12s)  The problem
// ==================================================================
function scene1(lt, a) {
  ctx.save(); ctx.globalAlpha = a;
  heading('The problem', 'Contributors bring agents you never chose.', ez(seg(lt, 0.2, 1.2)), lt);

  const agents = [
    { n: 'Claude Code', f: 'CLAUDE.md' },
    { n: 'Copilot',     f: 'copilot-instructions.md' },
    { n: 'Cursor',      f: '.cursorrules' },
    { n: 'Codex',       f: 'AGENTS.md' },
    { n: 'Gemini',      f: 'GEMINI.md' },
  ];
  const tw = 212, th = 150, gap = 22;
  const x0 = (W - (tw * 5 + gap * 4)) / 2, y0 = 220;
  const rule = '“don’t force-push to main”';

  agents.forEach((ag, i) => {
    const ta = ez(seg(lt, 1.2 + i * 0.28, 1.9 + i * 0.28));
    if (ta <= 0) return;
    ctx.save(); ctx.globalAlpha *= ta;
    const y = y0 + (1 - ezo(ta)) * 26;
    const x = x0 + i * (tw + gap);
    const rogue = (i === 2 && lt >= 8);           // Cursor goes rogue
    const flash = rogue ? 0.5 + 0.5 * Math.abs(Math.sin((lt - 8) * 5)) : 0;
    card(x, y, tw, th, 12, C.surf, rogue ? C.red : C.ov, rogue ? lerp(1.5, 3, flash) : 1.5);
    text(ag.n, x + tw / 2, y + 36, `600 19px ${SANS}`, C.text, 'center');
    text(ag.f, x + tw / 2, y + 62, `13px ${MONO}`, C.blue, 'center');

    // the same rule, copy-pasted into each file
    const ra = ez(seg(lt, 3.6 + i * 0.22, 4.2 + i * 0.22));
    if (ra > 0) {
      ctx.save(); ctx.globalAlpha *= ra;
      const dead = rogue ? ez(seg(lt, 8.4, 9.2)) : 0;
      ctx.globalAlpha *= (1 - dead * 0.55);
      text(rule, x + tw / 2, y + 100, `italic 12.5px ${SANS}`, dead > 0 ? C.dim : C.sub, 'center');
      if (dead > 0) {                              // strikethrough as it stops mattering
        ctx.strokeStyle = C.red; ctx.lineWidth = 1.6;
        const rw = ctx.measureText(rule).width;
        ctx.beginPath(); ctx.moveTo(x + tw / 2 - rw / 2, y + 96);
        ctx.lineTo(x + tw / 2 - rw / 2 + rw * dead, y + 96); ctx.stroke();
      }
      ctx.restore();
    }
    // the rogue action
    if (rogue) {
      const ga = ez(seg(lt, 8.2, 8.8));
      text('$ git push --force', x + tw / 2, y + 130, `13px ${MONO}`, C.red, 'center', ga);
    }
    ctx.restore();
  });

  // copy animation: the rule chip travels from center to the tiles
  const chipA = ez(seg(lt, 2.6, 3.2)) * (1 - ez(seg(lt, 5.2, 5.8)));
  if (chipA > 0) {
    ctx.save(); ctx.globalAlpha *= chipA;
    ctx.font = `italic 15px ${SANS}`;
    const cw = ctx.measureText(rule).width + 40;
    card(W / 2 - cw / 2, 430, cw, 44, 22, C.mantle, C.mauve, 1.5);
    text(rule, W / 2, 458, `italic 15px ${SANS}`, C.text, 'center');
    text('copy-pasted into every config file', W / 2, 500, `13px ${SANS}`, C.dim, 'center');
    ctx.restore();
  }

  // punchline
  const pa = ez(seg(lt, 9.4, 10.2));
  if (pa > 0) {
    text('Their volume scales with compute. Your review doesn’t.', W / 2, 610,
         `600 26px ${SANS}`, C.red, 'center', pa);
  }
  ctx.restore();
}

// ==================================================================
// SCENE 2  (12–22s)  Author once
// ==================================================================
const MANIFEST = [
  ['# .agents/policies/protect-main-branch/manifest.yaml', C.dim],
  ['id: protect-main-branch', null],
  ['name: "Protect Main Branch"', null],
  ['artifact: hook', null],
  ['enforcement: block', C.red],
  ['effects: [read_only]', C.teal],
  ['description: >', null],
  ['  Block direct commits and pushes to main', C.sub],
  ['  or master.', C.sub],
];
function scene2(lt, a) {
  ctx.save(); ctx.globalAlpha = a;
  heading('Governance as code', 'Author it once.', ez(seg(lt, 0.2, 1)), lt);

  const w = 720, h = 380, x = (W - w) / 2, y = 210;
  const o = windowFrame(x, y, w, h, 'manifest.yaml', ez(seg(lt, 0.5, 1.2)));
  ctx.font = `17px ${MONO}`;
  let cy = o.cy + 6;
  let charBudget = Math.max(0, (lt - 1.6) * 38);       // chars typed so far
  for (const [line, col] of MANIFEST) {
    const shown = line.substring(0, Math.floor(charBudget));
    charBudget -= line.length;
    if (shown.length > 0) {
      // yaml key/value tinting for full lines, plain while typing
      ctx.fillStyle = col || C.text;
      if (!col && shown.includes(':')) {
        const k = shown.split(':')[0] + ':';
        ctx.fillStyle = C.blue; ctx.fillText(k, o.cx + 8, cy);
        ctx.fillStyle = C.text; ctx.fillText(shown.slice(k.length), o.cx + 8 + ctx.measureText(k).width, cy);
      } else {
        ctx.fillText(shown, o.cx + 8, cy);
      }
    }
    cy += 34;
    if (charBudget < 0) break;
  }
  const pa = ez(seg(lt, 7.5, 8.3));
  text('A small, reviewable manifest — that is the whole policy.', W / 2, 650,
       `20px ${SANS}`, C.sub, 'center', pa);
  ctx.restore();
}

// ==================================================================
// SCENE 3  (22–34s)  Compile everywhere
// ==================================================================
function scene3(lt, a) {
  ctx.save(); ctx.globalAlpha = a;
  heading('The compiler', 'Compiled to every enforcement surface.', ez(seg(lt, 0.2, 1)), lt);

  // source manifest node (left)
  const mx = 170, my = 330, mw = 250, mh = 120;
  const ma = ez(seg(lt, 0.6, 1.3));
  ctx.save(); ctx.globalAlpha *= ma;
  card(mx, my, mw, mh, 12, C.surf, C.mauve, 2);
  text('manifest.yaml', mx + mw / 2, my + 40, `600 18px ${MONO}`, C.mauve, 'center');
  text('protect-main-branch', mx + mw / 2, my + 68, `14px ${MONO}`, C.text, 'center');
  text('enforcement: block', mx + mw / 2, my + 92, `13px ${MONO}`, C.red, 'center');
  ctx.restore();

  // four surfaces (right), lit in sequence
  const surfaces = [
    { n: 'git hook',            d: 'pre-commit · pre-push',      c: C.green },
    { n: 'CI gate',             d: 'commit-range backstop',      c: C.blue  },
    { n: 'Claude PreToolUse',   d: 'blocks the tool call',       c: C.peach },
    { n: 'AGENTS.md rules',     d: 'ambient, every agent',       c: C.yellow},
  ];
  const sx = 760, sw = 420, sh = 82, sgap = 22;
  const sy0 = 190;
  surfaces.forEach((s, i) => {
    const t0 = 1.6 + i * 1.5;
    const la = ez(seg(lt, t0, t0 + 0.6));
    if (la <= 0) return;
    const y = sy0 + i * (sh + sgap);
    // connecting line grows from manifest to surface
    const grow = ezo(seg(lt, t0, t0 + 0.7));
    ctx.save(); ctx.globalAlpha *= ez(seg(lt, t0, t0 + 0.3));
    ctx.strokeStyle = s.c; ctx.lineWidth = 2.5;
    ctx.beginPath();
    const x1 = mx + mw, y1 = my + mh / 2, x2 = sx, y2 = y + sh / 2;
    const midx = lerp(x1, x2, 0.5);
    // draw a curved connector, partially, by sampling
    const N = 40, upto = Math.floor(N * grow);
    for (let k = 0; k <= upto; k++) {
      const u = k / N;
      const px = (1-u)*(1-u)*x1 + 2*(1-u)*u*midx + u*u*x2;
      const py = (1-u)*(1-u)*y1 + 2*(1-u)*u*((y1+y2)/2 - 20) + u*u*y2;
      k === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
    }
    ctx.stroke();
    ctx.restore();

    ctx.save(); ctx.globalAlpha *= la;
    const pop = 1 + 0.04 * (1 - ezo(seg(lt, t0, t0 + 0.5)));
    ctx.translate(sx + sw / 2, y + sh / 2); ctx.scale(pop, pop); ctx.translate(-(sx + sw / 2), -(y + sh / 2));
    card(sx, y, sw, sh, 12, C.surf, s.c, 2);
    text(s.n, sx + 24, y + 36, `600 20px ${SANS}`, s.c);
    text(s.d, sx + 24, y + 62, `14px ${SANS}`, C.sub);
    text('✓', sx + sw - 34, y + 48, `600 26px ${SANS}`, s.c, 'center', ez(seg(lt, t0 + 0.5, t0 + 0.9)));
    ctx.restore();
  });

  // agent badge row
  const badges = ['Claude Code', 'Copilot', 'Cursor', 'Codex', 'Gemini', 'Aider', 'Windsurf', '+ 6 more'];
  const ba = ez(seg(lt, 8.4, 9.2));
  if (ba > 0) {
    ctx.save(); ctx.globalAlpha *= ba;
    text('13 agents, one source of truth', 80, 592, `600 16px ${SANS}`, C.sub);
    ctx.font = `14px ${SANS}`;
    let bx = 80;
    badges.forEach((b, i) => {
      const ia = ez(seg(lt, 8.6 + i * 0.18, 9.0 + i * 0.18));
      const wpx = ctx.measureText(b).width + 30;
      ctx.save(); ctx.globalAlpha *= ia;
      card(bx, 612, wpx, 36, 18, C.mantle, C.ov, 1.2);
      text(b, bx + wpx / 2, 635, `14px ${SANS}`, i === badges.length - 1 ? C.dim : C.text, 'center');
      ctx.restore();
      bx += wpx + 12;
    });
    ctx.restore();
  }
  ctx.restore();
}


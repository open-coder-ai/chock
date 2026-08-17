'use strict';
// ==================================================================
// SCENE 4  (34–48s)  Watch it enforce  — real captured output
// ==================================================================
const TERM = [
  // [start, kind, text]   kind: cmd (typed) | out | red | green | dim
  // Verbatim from the catalog README's real capture: a contributor's agent, in their
  // clone of your repo, stages a config file carrying a credential.
  [0.8,  'cmd',   'git commit -m "add config"'],
  [3.4,  'red',   'Potential secret detected in staged changes. Remove credentials'],
  [3.4,  'red',   'and rotate any exposed keys.'],
  [3.55, 'red',   '  - config.py: content pattern'],
  [7.6,  'cmd',   'git commit -m "read key from env"'],
  [10.6, 'green', '[PASS] All checks passed.'],
  [10.9, 'out',   '[feat/config b41f46e] read key from env'],
  [11.1, 'out',   ' 1 file changed, 2 insertions(+)'],
  [11.3, 'out',   ' create mode 100644 config.py'],
];
function scene4(lt, a) {
  ctx.save(); ctx.globalAlpha = a;
  heading('A contributor forks your repo', 'Their machine. Their agent. Your rules.', ez(seg(lt, 0.2, 1)), lt);

  // red flash on the frame when the block lands
  const blockAge = lt - 3.4;
  const flash = blockAge > 0 && blockAge < 1.2 ? (1 - blockAge / 1.2) : 0;
  const w = 900, h = 420, x = (W - w) / 2, y = 200;
  const o = windowFrame(x, y, w, h, '~/fork-of-your-repo — bash', ez(seg(lt, 0.4, 1)),
                        flash > 0 ? C.red : null);

  ctx.font = `17px ${MONO}`;
  let cy = o.cy + 4;
  const CPS = 30;
  for (const [t0, kind, s] of TERM) {
    if (lt < t0) break;
    if (kind === 'cmd') {
      const shown = typed(s, lt, t0, CPS);
      text('$ ', o.cx, cy, `17px ${MONO}`, C.green);
      text(shown, o.cx + 20, cy, `17px ${MONO}`, C.text);
      if (shown.length < s.length && (lt * 2) % 1 < 0.5) {
        ctx.fillStyle = C.text;
        ctx.fillRect(o.cx + 20 + ctx.measureText(shown).width + 2, cy - 15, 9, 19);
      }
    } else {
      const col = kind === 'red' ? C.red : kind === 'green' ? C.green : kind === 'dim' ? C.dim : C.sub;
      const weight = kind === 'red' || kind === 'green' ? '600 ' : '';
      text(s, o.cx, cy, `${weight}17px ${MONO}`, col, 'left', ez(seg(lt, t0, t0 + 0.25)));
    }
    cy += 30;
  }

  const pa = ez(seg(lt, 5.2, 6.0)) * (1 - ez(seg(lt, 7.2, 7.8)));
  if (pa > 0) text('Blocked on their machine — before the PR exists.', W / 2, 668, `600 24px ${SANS}`, C.red, 'center', pa);
  const pb = ez(seg(lt, 11.6, 12.4));
  if (pb > 0) text('What reaches you has already passed your gates.', W / 2, 668, `600 24px ${SANS}`, C.green, 'center', pb);
  ctx.restore();
}

// ==================================================================
// SCENE 5  (48–58s)  Proof, not promises
// ==================================================================
function scene5(lt, a) {
  ctx.save(); ctx.globalAlpha = a;
  heading('Proof, not promises', 'Coverage you can prove — per agent, per policy.', ez(seg(lt, 0.2, 1)), lt);

  // left: coverage report  (real `chock sync` output)
  const w1 = 560, h1 = 300, x1 = 80, y1 = 220;
  const o = windowFrame(x1, y1, w1, h1, 'chock sync --repo .', ez(seg(lt, 0.5, 1.2)));
  const rows = [
    ['protect-main-branch:', C.text, 0],
    ['  claude:  enforced-at-commit', C.green, 1],
    ['  copilot: enforced-at-commit', C.green, 2],
    ['  gemini:  enforced-at-commit', C.green, 3],
  ];
  rows.forEach(([s, col, i]) => {
    const ra = ez(seg(lt, 1.2 + i * 0.5, 1.6 + i * 0.5));
    text(s, o.cx, o.cy + 10 + i * 38, `600 18px ${MONO}`, col, 'left', ra);
  });
  const legend = [['enforced', C.green], ['enforced-at-commit', C.teal], ['advisory', C.yellow]];
  let lx = o.cx;
  ctx.font = `14px ${SANS}`;
  legend.forEach(([s, col]) => {
    const la = ez(seg(lt, 3.4, 4.0));
    ctx.save(); ctx.globalAlpha *= la;
    ctx.beginPath(); ctx.arc(lx + 6, o.cy + 185, 5, 0, 7); ctx.fillStyle = col; ctx.fill();
    text(s, lx + 18, o.cy + 190, `14px ${SANS}`, C.sub);
    ctx.restore();
    ctx.font = `14px ${SANS}`;
    lx += 18 + ctx.measureText(s).width + 26;
  });

  // right: eval suite dots
  const x2 = 720, y2 = 220, w2 = 480;
  const ea = ez(seg(lt, 4.2, 4.9));
  ctx.save(); ctx.globalAlpha *= ea;
  card(x2, y2, w2, 300, 12, C.surf, C.ov, 1.5);
  text('eval suite — replayed on every build', x2 + 30, y2 + 46, `600 19px ${SANS}`, C.text);
  const cases = ['blocks commit on main', 'blocks push to master', 'allows feature branch',
                 'respects protected_branches config', 'adversarial: --no-verify bypass'];
  cases.forEach((cse, i) => {
    const ca = ez(seg(lt, 5.0 + i * 0.55, 5.4 + i * 0.55));
    if (ca <= 0) return;
    ctx.save(); ctx.globalAlpha *= ca;
    const yy = y2 + 90 + i * 40;
    text('✓', x2 + 36, yy, `600 20px ${SANS}`, C.green, 'center');
    text(cse, x2 + 58, yy, `16px ${SANS}`, C.sub);
    ctx.restore();
  });
  ctx.restore();

  const pa = ez(seg(lt, 8.0, 8.7));
  text('It prints what is NOT covered, too. Honesty is the feature.', W / 2, 650,
       `20px ${SANS}`, C.sub, 'center', pa);
  ctx.restore();
}

// ==================================================================
// SCENE 6  (58–68s)  The catalog
// ==================================================================
function scene6(lt, a) {
  ctx.save(); ctx.globalAlpha = a;
  heading('The catalog', 'Ready-made guardrails, one command away.', ez(seg(lt, 0.2, 1)), lt);

  const pols = [
    ['protect-main-branch', 'hook · block', C.green],
    ['scan-secrets', 'hook · block', C.green],
    ['block-destructive-commands', 'hook · block', C.green],
    ['block-no-verify', 'rule · block', C.green],
    ['code-safety', 'rule · advisory', C.yellow],
    ['git-safety', 'rule · advisory', C.yellow],
    ['token-efficiency', 'rule · advisory', C.yellow],
    ['commit-message-style', 'skill · evals', C.blue],
  ];
  const cw = 272, ch = 96, gx = 24, gy = 22;
  const x0 = (W - (cw * 4 + gx * 3)) / 2, y0 = 200;
  pols.forEach(([n, k, col], i) => {
    const t0 = 0.6 + i * 0.28;
    const ca = ez(seg(lt, t0, t0 + 0.5));
    if (ca <= 0) return;
    ctx.save(); ctx.globalAlpha *= ca;
    const x = x0 + (i % 4) * (cw + gx), y = y0 + Math.floor(i / 4) * (ch + gy) + (1 - ezo(ca)) * 18;
    card(x, y, cw, ch, 10, C.surf, C.ov, 1.2);
    text(n, x + 20, y + 38, `600 15px ${MONO}`, C.text);
    text(k, x + 20, y + 66, `13px ${SANS}`, col);
    ctx.restore();
  });

  // OWASP banner
  const ba = ez(seg(lt, 4.2, 5.0));
  if (ba > 0) {
    ctx.save(); ctx.globalAlpha *= ba;
    const bw = 1040, bh = 120, bx = (W - bw) / 2, by = 470;
    card(bx, by, bw, bh, 12, C.mantle, C.mauve, 2);
    text('agentic-security pack', bx + 36, by + 46, `600 20px ${SANS}`, C.mauve);
    text('OWASP Top 10 for Agentic Applications — all 10 controls covered, honestly labeled',
         bx + 36, by + 80, `18px ${SANS}`, C.text);
    // 10 ticks
    for (let i = 0; i < 10; i++) {
      const ta = ez(seg(lt, 5.2 + i * 0.22, 5.5 + i * 0.22));
      text('✓', bx + 700 + i * 30, by + 46, `600 22px ${SANS}`, C.green, 'center', ta);
    }
    text('A growing catalog — every policy ships an eval suite and an adoption transcript',
         W / 2, 650, `18px ${SANS}`, C.sub, 'center', ez(seg(lt, 7.6, 8.3)));
    ctx.restore();
  }
  ctx.restore();
}

// ==================================================================
// SCENE 7  (68–75s)  CTA
// ==================================================================
function scene7(lt, a) {
  ctx.save(); ctx.globalAlpha = a;
  const la = ez(seg(lt, 0.2, 1.0));
  logo(W / 2 - 12, 188, 2.0, la, true);
  text('Chock', W / 2, 350, `700 64px ${SANS}`, C.text, 'center', ez(seg(lt, 0.5, 1.2)));
  text('Review the policy once — not every pull request.', W / 2, 405, `24px ${SANS}`, C.sub, 'center', ez(seg(lt, 1.0, 1.7)));
  const pa = ez(seg(lt, 1.6, 2.3));
  if (pa > 0) {
    ctx.save(); ctx.globalAlpha *= pa;
    ctx.font = `600 22px ${MONO}`;
    const s = 'pip install chock';
    const pw = ctx.measureText(s).width + 76;
    card(W / 2 - pw / 2, 445, pw, 56, 28, C.crust, C.green, 2);
    text('$', W / 2 - pw / 2 + 28, 481, `600 22px ${MONO}`, C.green);
    text(s, W / 2 - pw / 2 + 52, 481, `600 22px ${MONO}`, C.text);
    ctx.restore();
  }
  text('github.com/open-coder-ai/chock   ·   chock.sh', W / 2, 560,
       `18px ${SANS}`, C.dim, 'center', ez(seg(lt, 2.2, 2.9)));
  ctx.restore();
}


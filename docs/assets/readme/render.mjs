// Renders the dusk README panels to PNG. Numbers come from data.json (derive.py); nothing is typed here.
// Usage: node docs/assets/readme/render.mjs   (needs `playwright`; CHROMIUM=/path to use a preinstalled Chromium)
import { chromium } from 'playwright';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = process.env.OUT_DIR || HERE;
const D = JSON.parse(readFileSync(path.join(HERE, 'data.json'), 'utf8'));
const fmt = (n) => n.toLocaleString('en-US');
const chipsCatalog = [`${D.policies} policies`, `${fmt(D.eval_cases)} eval cases`, `${D.tiers.commit} enforced at commit`, 'Apache-2.0'];

const CSS = `
*{box-sizing:border-box}
body{margin:0;background:#222C44;color:#EEF1F6;font-family:"Instrument Sans",system-ui,sans-serif}
.mono{font-family:"JetBrains Mono",ui-monospace,monospace}
.frame{width:1200px;padding:56px 60px;background:#222C44}
.eyebrow{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:15px;letter-spacing:.14em;text-transform:uppercase;color:#F0B53C}
h1{margin:0;font-size:52px;line-height:1.05;font-weight:700;letter-spacing:-.03em}
h2{margin:0;font-size:38px;line-height:1.1;font-weight:600;letter-spacing:-.02em}
.gold{color:#F0B53C}
.sub{margin:0;font-size:21px;line-height:1.5;color:#B4BED2}
.chip{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:15px;padding:7px 12px;border:1px solid #3A4870;border-radius:7px;background:#263251;color:#D5DBE8;white-space:nowrap}
.panel{border:1px solid #3A4870;border-radius:16px;background:#263251}
.term{border:1px solid #3A4870;border-radius:14px;background:#1A2238;padding:24px 26px;font-family:"JetBrains Mono",ui-monospace,monospace;font-size:16px;line-height:1.75}
.d{color:#F0B53C}.no{color:#F29B8A}.c{color:#7F8CA8}
.tier{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:12.5px;font-weight:600;padding:3px 8px;border-radius:5px;white-space:nowrap}
.tc{background:#F0B53C;color:#222C44}.ta{background:#8FB4F0;color:#222C44}.td{background:#3A4870;color:#EEF1F6}
`;
const MARK = `<svg width="46" height="46" viewBox="0 0 512 512" aria-hidden="true"><rect width="512" height="512" rx="104" fill="#263251"/><path d="M 210.1 183.2 L 156.2 256.0 L 210.1 328.8" fill="none" stroke="#F0B53C" stroke-width="24.76" stroke-linecap="round" stroke-linejoin="round"/><path d="M 301.9 183.2 L 355.8 256.0 L 301.9 328.8" fill="none" stroke="#F0B53C" stroke-width="24.76" stroke-linecap="round" stroke-linejoin="round"/><rect x="227.25" y="227.25" width="57.51" height="57.51" transform="rotate(45 256 256)" fill="#F0B53C"/></svg>`;
const page = (body) => `<!doctype html><html lang="en"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>${CSS}</style></head><body>${body}</body></html>`;
const term = (rows, note) => `<div class="term">${rows.join('')}${note ? `<div class="c" style="margin-top:10px">${note}</div>` : ''}</div>`;
const cmd = (l) => `<div><span class="d">❯</span> ${l}</div>`;
const tierClass = { commit: 'tc', 'in-agent': 'ta', advisory: 'td' };
const tag = (t) => `<span class="tier ${tierClass[t]}">${t}</span>`;

const REFUSALS = term([
  '<div class="c"># what a refusal looks like</div>',
  cmd('git commit -m config'), '<div class="no">✗ AWS access key in config.py</div>',
  cmd('git commit -m infra'), '<div class="no">✗ IAM Action "*" on Resource "*"</div>',
  cmd('git commit -m mcp'), '<div class="no">✗ MCP server pinned to @latest</div>',
]);

function cover({ repo, title, sub, chips, right }) {
  return page(`<div class="frame" style="display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:48px;align-items:center;padding:64px 60px">
<div style="display:flex;flex-direction:column;gap:26px">
<div style="display:flex;align-items:center;gap:14px">${MARK}<span class="mono" style="font-size:22px;font-weight:600">${repo}</span></div>
<h1>${title}</h1><p class="sub">${sub}</p>
<div style="display:flex;flex-wrap:wrap;gap:10px">${chips.map((c) => `<span class="chip">${c}</span>`).join('')}</div></div>
<div>${right}</div></div>`);
}

const COVERS = {
  'cover-chock': cover({ repo: 'chock', title: 'Teach your AI agent <span class="gold">what not to do.</span>',
    sub: 'Rules the agent reads, checks that run as it writes, and gates at commit and in CI. One policy, every coding agent.',
    chips: ['no LLM, no tokens', 'git hook + CI gate', 'Apache-2.0'], right: REFUSALS }),
  'cover-org': cover({ repo: 'open-coder-ai', title: 'Teach your AI agent <span class="gold">what not to do.</span>',
    sub: 'Open-source guardrails for AI coding agents: policies, the primitives under them, and the evidence they work.', chips: chipsCatalog, right: REFUSALS }),
  'cover-chock-catalog': cover({ repo: 'chock-catalog', title: `${D.policies} policies <span class="gold">for AI-written code.</span>`,
    sub: 'Each one labelled by what it enforces: at commit, in the agent, or advice the agent reads.', chips: chipsCatalog,
    right: term([`<div class="c"># tiers, from registry.yaml</div>`, `<div><span class="d">${D.tiers.commit}</span> enforced at commit</div>`, `<div><span class="d">${D.tiers['in-agent']}</span> in the agent, best-effort</div>`, `<div><span class="d">${D.tiers.advisory}</span> advisory</div>`, `<div class="c" style="margin-top:10px">${fmt(D.eval_executed)} of ${fmt(D.eval_cases)} eval cases replay automatically</div>`]) }),
  'cover-agentseam': cover({ repo: 'agentseam', title: 'Write a guard once. <span class="gold">Run it in the agent you use.</span>',
    sub: 'One handler API over each agent\'s hooks, instruction files and config, with an honest matrix of where a guard can block.', chips: ['stdlib-only', 'Apache-2.0'],
    right: term(['<div><span class="d">def</span> handler(event):</div>', '<div>&nbsp;&nbsp;<span class="d">if</span> unsafe_write(event):</div>', '<div>&nbsp;&nbsp;&nbsp;&nbsp;<span class="d">return</span> Decision.deny("…")</div>', '<div>&nbsp;&nbsp;<span class="d">return</span> Decision.allow()</div>']) }),
  'cover-context-report': cover({ repo: 'context-report', title: 'Signed evidence that an <span class="gold">agent plugin works.</span>',
    sub: 'Reachability, fault behaviour, cost and efficacy for plugins, hooks, skills and MCP servers, as rows anyone can re-derive.', chips: ['in-toto', 'Sigstore', 'Apache-2.0'],
    right: term(['<div class="c"># one report, row by row</div>', '<div><span class="d">reachable</span> verified or claimed</div>', '<div><span class="d">fault</span> verified or claimed</div>', '<div><span class="d">cost</span> verified or claimed</div>']) }),
  'cover-chock-threat-intel': cover({ repo: 'chock-threat-intel', title: 'Every new agentic threat, <span class="gold">scored against a policy.</span>',
    sub: 'A weekly, human-reviewed ledger: each entry marked enforced, advisory, or policy wanted.', chips: ['weekly', 'human-reviewed', 'Apache-2.0'],
    right: term(['<div class="c"># ledger status</div>', `<div>${tag('commit')} enforced (a slice)</div>`, `<div>${tag('advisory')} advice only</div>`, '<div><span class="tier td">policy wanted</span> no policy yet</div>']) }),
  'cover-chock-quickstart': cover({ repo: 'chock-quickstart', title: 'Start a repo with guardrails <span class="gold">in 60 seconds.</span>',
    sub: 'Exactly what chock init leaves behind. Then turn on the checks your stack needs.', chips: ['template repo', 'no policies preinstalled'],
    right: term([cmd('chock sync --repo .'), cmd('chock add &lt;id&gt; --ref &lt;sha&gt;'), cmd('chock sync --repo .')], 'git never clones hooks. sync wires them.') }),
  'cover-chock-example': cover({ repo: 'chock-example', title: 'A working Chock adoption, <span class="gold">end to end.</span>',
    sub: 'One policy per layer, small enough to read in one sitting and ready to copy.', chips: ['template repo', 'hook · rule · skill'], right: REFUSALS }),
};

const card = (n, t, p, pols) => `<div class="panel" style="padding:24px;display:flex;flex-direction:column;gap:12px">
<div style="display:flex;gap:10px;align-items:baseline"><span class="mono gold" style="font-size:14px">${n}</span><span style="font-size:22px;font-weight:600">${t}</span></div>
<div style="font-size:16.5px;line-height:1.5;color:#B4BED2;flex-grow:1">${p}</div>
<div style="display:flex;flex-wrap:wrap;gap:8px">${pols.map(([id, tier]) => `<span class="mono" style="display:inline-flex;gap:8px;align-items:center;font-size:13.5px;padding:5px 8px;border:1px solid #3A4870;border-radius:6px;background:#222C44">${id} ${tag(tier)}</span>`).join('')}</div></div>`;
const T = Object.fromEntries(D.incidents.map((i) => [i.policy, i.tier]));
const APPSEC = page(`<div class="frame" style="display:flex;flex-direction:column;gap:30px">
<div style="display:flex;justify-content:space-between;align-items:flex-end;gap:30px"><div style="display:flex;flex-direction:column;gap:12px"><span class="eyebrow">What it stops</span><h2>Application security first.</h2></div>
<div style="display:flex;gap:10px">${tag('commit')}${tag('in-agent')}${tag('advisory')}</div></div>
<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px">
${card('01', 'Java &amp; Kotlin', 'Injection, XXE, SSRF, unsafe deserialization, weak crypto, disabled Spring Security, dependencies below a known fix.', [['java-security', T['java-security']]])}
${card('02', 'Unsafe code &amp; IAM', 'eval, shell=True, os.system, pickle; IAM Action:*, AdministratorAccess, roles/owner.', [['block-unsafe-code-execution', 'commit'], ['block-wildcard-iam', T['block-wildcard-iam']]])}
${card('03', 'Supply chain', 'Dependencies not on an allowlist, Actions on a mutable tag, MCP servers and images at @latest.', [['verify-dependency-exists', 'commit'], ['pin-github-actions', T['pin-github-actions']], ['block-unpinned-agent-components', T['block-unpinned-agent-components']]])}
${card('04', 'Agent code', 'Code that builds agents: host execution, unpinned MCP servers, approvals switched off, credential leaks.', [['agentic-code-security', 'commit']])}
${card('05', 'OWASP Agentic Top 10', `A policy for each of ASI01 to ASI10. ${D.asi.refused_at_commit.length} have a slice refused at commit. ${D.asi.fully_covered} are fully covered.`, [['owasp-asi01…10', 'advisory']])}
${card('06', 'Accessibility', 'A change that strips an alt, aria-label, label or lang an element already had is refused.', [['no-a11y-regression', 'commit']])}
${card('07', 'Prompt injection &amp; memory', 'Bidi and tag characters that hide instructions; secrets and pasted history written into agent memory.', [['block-invisible-unicode', T['block-invisible-unicode']], ['guard-memory-writes', 'commit']])}
${card('08', 'Test integrity', 'Deleted tests, net assertion loss, assert True, new skip and .only markers.', [['protect-test-integrity', 'commit']])}
${card('09', 'Also included', 'Secrets, destructive commands, hook bypass, agent self-protection, EU AI Act.', [['scan-secrets', T['scan-secrets']], ['block-destructive-commands', 'commit'], ['protect-agent-config', 'in-agent']])}
</div></div>`);

const ADOPT = page(`<div class="frame" style="display:flex;flex-direction:column;gap:30px">
<div style="display:flex;flex-direction:column;gap:12px"><span class="eyebrow">Get started</span><h2>Two ways to adopt it.</h2></div>
<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px">
<div class="panel" style="padding:30px;display:flex;flex-direction:column;gap:18px;border-color:#F0B53C">
<div style="display:flex;justify-content:space-between;align-items:center"><span class="eyebrow">Route 1</span><span class="mono" style="font-size:13px;padding:5px 10px;border-radius:999px;background:#F0B53C;color:#222C44">for teams</span></div>
<div style="font-size:28px;font-weight:600">In your repository</div>
${term([cmd('chock init .'), cmd('chock add &lt;id&gt; --ref &lt;sha&gt; \\'), '<div>&nbsp;&nbsp;--verify-sha &lt;sha256&gt; --skip-compile</div>', cmd('chock sync --repo . --ci')])}
<div style="font-size:17px;line-height:1.55;color:#D5DBE8">Everyone and every agent on the repo. Enforced at commit and in CI. Travels with every clone.</div></div>
<div class="panel" style="padding:30px;display:flex;flex-direction:column;gap:18px">
<div style="display:flex;justify-content:space-between;align-items:center"><span class="eyebrow">Route 2</span><span class="mono" style="font-size:13px;padding:5px 10px;border-radius:999px;border:1px solid #3A4870;color:#D5DBE8">no repo changes</span></div>
<div style="font-size:28px;font-weight:600">In your coding agent, as plugins</div>
${term(['<div class="d">Claude Code</div>', '<div>chock-claude-plugins</div>', '<div class="d">Cursor · Copilot · Codex · Devin</div>', '<div>one plugin repo per client</div>'])}
<div style="font-size:17px;line-height:1.55;color:#D5DBE8">Your own sessions in that client. Best-effort hooks that fail open. Pair with route 1 for commit and CI.</div></div>
</div>
<div class="panel" style="padding:20px 28px;font-size:18px;color:#D5DBE8"><span class="gold" style="font-weight:600">Or build a selection:</span> the chock.sh builder (launching soon) gives one Claude Code plugin from the policies you pick.</div></div>`);

const role = (t, s, lines) => `<div class="panel" style="padding:26px;display:flex;flex-direction:column;gap:12px">
<div style="font-size:23px;font-weight:600">${t}</div><div class="mono" style="font-size:13.5px;color:#B4BED2">${s}</div>
${lines.map(([k, v]) => `<div style="display:grid;grid-template-columns:96px minmax(0,1fr);gap:12px;padding-top:10px;border-top:1px solid #3A4870;font-size:16px;line-height:1.5;color:#D5DBE8"><span class="mono gold" style="font-size:12.5px;letter-spacing:.06em;text-transform:uppercase;padding-top:3px">${k}</span><span>${v}</span></div>`).join('')}</div>`;
const ROLES = page(`<div class="frame" style="display:flex;flex-direction:column;gap:30px">
<div style="display:flex;flex-direction:column;gap:12px"><span class="eyebrow">A normal day, by role</span><h2>What changes for the people who ship with agents.</h2></div>
<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px">
${role('Java &amp; Kotlin developers', 'Spring · Jakarta · Quarkus · Micronaut · Android', [['Agent', 'puts ${id} into a MyBatis query'], ['Chock', 'refuses it at commit, naming the rule'], ['You get', 'the finding in the agent\'s turn, not in a scan a day later']])}
${role('Web &amp; UX designers', 'ADA · Section 508 · WCAG', [['Agent', 'empties an alt or drops an aria-label in a refactor'], ['Chock', 'refuses the change and names the element'], ['You get', 'accessibility fixes that can\'t quietly regress']])}
${role('Agent memory', 'CLAUDE.md · MEMORY.md · the agent\'s own stores', [['Agent', 'writes a pasted diff or an API key into memory'], ['Chock', 'refuses the write'], ['You get', 'memory that stays small and secret-free']])}
${role('AppSec &amp; OWASP owners', 'OWASP Top 10 for Agentic Applications', [['Today', 'a checklist in a wiki, followed or not'], ['Chock', 'a policy for each ASI01 to ASI10 risk, in the repo'], ['You get', 'a checklist that runs on every commit; every mapping labelled partial']])}
${role('Threat modeling', 'MITRE ATLAS', [['Maps', 'techniques to named policies'], ['Weekly', 'every new entry scored enforced, advisory or policy wanted'], ['You get', 'from technique ID to the control that answers it']])}
${role('Platform &amp; governance', 'Policy as code, with an audit trail', [['Chock', 'one policy becomes a git hook, a CI gate and agent hooks'], ['Pinned', 'hash-pinned installs in chock.lock'], ['You get', 'a coverage grade per policy and agent, with evidence']])}
</div></div>`);

const row = (k, a, b) => `<div style="display:grid;grid-template-columns:190px minmax(0,1fr) minmax(0,1.25fr);gap:24px;padding:18px 26px;border-top:1px solid #3A4870;font-size:17px;line-height:1.5"><span style="font-weight:600;color:#D5DBE8">${k}</span><span style="color:#B4BED2">${a}</span><span>${b}</span></div>`;
const COMPARE = page(`<div class="frame" style="display:flex;flex-direction:column;gap:30px">
<div style="display:flex;flex-direction:column;gap:12px"><span class="eyebrow">More than a blocklist</span><h2>Open, deterministic, <span class="gold">in your repo.</span></h2></div>
<div class="panel" style="overflow:hidden">
<div style="display:grid;grid-template-columns:190px minmax(0,1fr) minmax(0,1.25fr);gap:24px;padding:16px 26px;background:#2D3A5E" class="mono"><span></span><span style="font-size:13px;letter-spacing:.1em;color:#B4BED2">AGENT DEFAULTS</span><span class="gold" style="font-size:13px;letter-spacing:.1em">WITH CHOCK</span></div>
${row('What it knows', 'Generic shell prompts', 'Your stack')}
${row('Where it lives', 'One person\'s settings', 'Plain files in the repo, reviewed in pull requests')}
${row('Which agents', 'Each agent, its own format', 'One policy compiled for all')}
${row('After the agent', 'Nothing', 'A git hook and a CI gate')}
${row('When it says no', 'A yes/no prompt', 'A refusal that names the fix')}
${row('Proof', 'None', 'Eval cases replayed in CI, and a coverage grade per agent')}
</div></div>`);

const step = (t, hot) => `<div class="panel" style="padding:16px 18px;font-size:17px;text-align:center;flex:1;${hot ? 'border-color:#F0B53C;color:#F0B53C;font-weight:600' : ''}">${t}</div>`;
const arrow = '<span class="c" style="font-size:22px">→</span>';
const lane = (label, steps) => `<div style="display:flex;flex-direction:column;gap:12px"><span class="mono" style="font-size:14px;color:#B4BED2;letter-spacing:.1em;text-transform:uppercase">${label}</span><div style="display:flex;align-items:center;gap:12px">${steps.join(arrow)}</div></div>`;
const PIPELINE = page(`<div class="frame" style="display:flex;flex-direction:column;gap:34px">
<div style="display:flex;flex-direction:column;gap:12px"><span class="eyebrow">Shift left, without a model</span><h2>Fix the known classes <span class="gold">in the agent's turn.</span></h2></div>
${lane('Today', [step('Agent writes'), step('Human review'), step('SAST in CI'), step('Security review'), step('Release')])}
${lane('With Chock', [step('Agent writes'), step('Check runs: refusal names the fix', true), step('Agent fixes it, same turn'), step('Review sees the rest'), step('Release')])}
<div style="font-size:18px;line-height:1.55;color:#B4BED2">A check is a deterministic script, not a model call. A passing check adds nothing to the agent's context; a refusal adds one short reason.</div></div>`);

const ALL = { ...COVERS, appsec: APPSEC, adopt: ADOPT, roles: ROLES, compare: COMPARE, pipeline: PIPELINE };
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
const pg = await browser.newPage({ viewport: { width: 1200, height: 800 }, deviceScaleFactor: 2 });
for (const [name, html] of Object.entries(ALL)) {
  await pg.setContent(html, { waitUntil: 'networkidle' });
  await pg.evaluate(() => document.fonts.ready);
  await pg.locator('.frame').screenshot({ path: path.join(OUT, `${name}.png`) });
  console.log(`${name}.png`);
}
await browser.close();

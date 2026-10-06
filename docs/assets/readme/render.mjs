// Renders the dusk README panels to PNG. Numbers come from data.json (derive.py); nothing is typed here.
// Usage: [ONLY=name,name] node docs/assets/readme/render.mjs   (needs `playwright`; CHROMIUM=/path to use a preinstalled Chromium)
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

const SPECS = [];
function cover({ repo, title, sub, chips, right }) {
  SPECS.push({ repo, title, sub, chips, right });
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


const SECTION = (eyebrow, title, body) => page(`<div class="frame" style="display:flex;flex-direction:column;gap:30px">
<div style="display:flex;flex-direction:column;gap:12px"><span class="eyebrow">${eyebrow}</span><h2>${title}</h2></div>${body}</div>`);
const grid = (cols, gap, items) => `<div style="display:grid;grid-template-columns:repeat(${cols},minmax(0,1fr));gap:${gap}px">${items.join('')}</div>`;
const stat = (n, label) => `<div class="panel" style="padding:22px 24px;display:flex;flex-direction:column;gap:6px"><span class="mono gold" style="font-size:40px;font-weight:600">${n}</span><span style="font-size:16px;color:#B4BED2;line-height:1.4">${label}</span></div>`;
const note = (t) => `<div style="font-size:18px;line-height:1.55;color:#B4BED2">${t}</div>`;

const refusal = (id, tier, msg) => `<div class="panel" style="padding:24px;display:flex;flex-direction:column;gap:14px">
<div style="display:flex;justify-content:space-between;align-items:center"><span class="mono" style="font-size:15px;font-weight:600">${id}</span>${tag(tier)}</div>
<div style="font-size:18.5px;line-height:1.55;color:#D5DBE8">&ldquo;${msg}&rdquo;</div></div>`;
const REFUSAL = SECTION('Guardrails that teach', 'A refusal that <span class="gold">tells the agent the fix.</span>', `
<p class="sub">Each refusal names the safe alternative, so the agent can fix it in the same turn. Messages are quoted from the policy manifests in chock-catalog.</p>
${grid(2, 18, [
  refusal('block-unsafe-code-execution', 'commit', 'Dynamic execution primitive detected. Replace it with a parameterized API (a subprocess argument vector without a shell, yaml.safe_load, a real parser&hellip;)'),
  refusal('block-unpinned-agent-components', 'commit', 'Unpinned agent component detected. Pin an exact version or digest (name@1.2.3, image:1.27.1&hellip;) so what runs tomorrow is what was reviewed today'),
  refusal('block-wildcard-iam', 'commit', 'Broad privilege grant detected. Name the actions and resources the task needs (no wildcard action, resource or principal&hellip;)'),
  refusal('scan-secrets', 'commit', 'Potential secret detected in this change. Remove credentials and rotate any exposed keys.'),
])}`);

const layer = (name, line, hot) => `<div class="panel" style="padding:20px 26px;display:grid;grid-template-columns:230px minmax(0,1fr);gap:24px;align-items:center;${hot ? 'border-color:#F0B53C' : ''}"><span class="mono${hot ? ' gold' : ''}" style="font-size:19px;font-weight:600">${name}</span><span style="font-size:17.5px;line-height:1.5;color:#D5DBE8">${line}</span></div>`;
const LAYERS = SECTION('The stack', 'One layer underneath. Governance on top. <span class="gold">Evidence all the way through.</span>', `
<div style="display:flex;flex-direction:column;gap:12px">
${layer('Evidence', 'context-report: a signed report of whether a plugin, hook or skill works. chock-threat-intel: a weekly ledger of threats, scored against the catalog.')}
${layer('Your agents', 'Claude Code, Cursor, Copilot, Codex, Gemini, Windsurf, Devin and the rest of the matrix.')}
${layer('Plugins', 'One generated repo per client: Claude Code, Cursor, Copilot, Codex, Devin.')}
${layer('chock-catalog', `${D.policies} policies, each labelled by what it enforces. Installed with <span class="mono">chock add &lt;id&gt;</span>.`)}
${layer('chock', 'Governance as code: one policy becomes a git hook, a CI gate, native agent hooks and an AGENTS.md rule.', true)}
${layer('agentseam', 'The primitives: one handler API over each agent\'s hooks, instruction files, plugin packaging and config.')}
${layer('Templates', 'chock-quickstart is what chock init leaves behind. chock-example is a working adoption.')}
</div>`);

const QUICKSTART = SECTION('See it work', 'Two commands. Real hooks. <span class="gold">Real refusals.</span>', `
<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px">
${term(['<div class="c"># set up once</div>', cmd('chock init .'), cmd('chock add scan-secrets --ref &lt;sha&gt; \\'), '<div>&nbsp;&nbsp;--verify-sha &lt;sha256&gt; --skip-compile</div>', cmd('chock sync --repo . --ci')], 'git never clones hooks. Every clone runs chock sync --repo . once.')}
${term(['<div class="c"># the next commit with a credential</div>', cmd('git commit -m "add config"'), '<div class="no">✗ Potential secret detected in this change.</div>', '<div class="no">&nbsp;&nbsp;- config.py: content pattern</div>', cmd('git commit -m "read key from env"'), '<div class="d">✓ passes</div>'])}
</div>
${note('The refusal text is the gate message of scan-secrets in chock-catalog. The recording is in the text version.')}`);

const GRADE_ROWS = [['enforced', 'a verified fail-closed block', 'tc'], ['enforceable', 'can block and can be set to fail closed', 'ta'], ['best-effort', 'can block, but fails open', 'ta'], ['detect', 'observable after the fact', 'td'], ['none', 'no hook surface', 'td']];
const A = D.agentseam;
const MATRIX = SECTION('Honest by construction', 'A capability matrix that <span class="gold">refuses to flatter anyone.</span>', `
<p class="sub">${A.agents} agents &times; ${A.events} lifecycle events = ${A.cells} cells. A cell is graded only as high as its evidence supports: vendor docs cannot back &ldquo;enforced&rdquo;.</p>
${grid(5, 14, GRADE_ROWS.map(([g, what, c]) => `<div class="panel" style="padding:20px 18px;display:flex;flex-direction:column;gap:8px"><span class="tier ${c}" style="align-self:flex-start">${g}</span><span class="mono gold" style="font-size:40px;font-weight:600">${A.grades[g]}</span><span style="font-size:15.5px;line-height:1.4;color:#B4BED2">${what}</span></div>`))}
${note(`${A.grades.enforced} cells are graded &ldquo;enforced&rdquo;. We say so rather than pretend a guardrail holds where it does not. Counted with matrix.enforcement_level() at agentseam ${A.source.commit.slice(0, 7)}.`)}`);

const CATEGORIES = [['Base guardrails', 'Secrets, destructive commands, protected branches, test integrity, supply chain.'], ['Agentic security', 'Code that builds agents, wildcard IAM, unsafe execution, and the OWASP Agentic Top 10.'], ['Agent discipline and compliance', 'Context hygiene, memory rules, config protection, and EU AI Act triage.']];
const CATALOG = SECTION('The policy catalog', 'Policies that stop your agent doing what <span class="gold">you would have caught in review.</span>', `
${grid(3, 16, [[D.tiers.commit, 'enforced at commit: a git hook exits non-zero', 'commit'], [D.tiers['in-agent'], 'in the agent: best-effort, fails open', 'in-agent'], [D.tiers.advisory, 'advisory: rule text the agent reads', 'advisory']].map(([n, l, t]) => `<div class="panel" style="padding:24px;display:flex;flex-direction:column;gap:10px">${tag(t)}<span class="mono gold" style="font-size:52px;font-weight:600">${n}</span><span style="font-size:17px;color:#D5DBE8">${l}</span></div>`))}
${grid(3, 16, CATEGORIES.map(([t, p]) => `<div class="panel" style="padding:22px;display:flex;flex-direction:column;gap:8px"><span style="font-size:20px;font-weight:600">${t}</span><span style="font-size:16px;line-height:1.5;color:#B4BED2">${p}</span></div>`))}
${note(`${D.policies} policies, from registry.yaml in chock-catalog at ${D.source.commit.slice(0, 7)}. ${fmt(D.eval_executed)} of ${fmt(D.eval_cases)} eval cases replay automatically.`)}`);

const FAMILY = SECTION('Everything we ship', `${D.repos.length} public repositories.`, `
${grid(3, 14, D.repos.map((r) => `<div class="panel" style="padding:18px 20px;display:flex;flex-direction:column;gap:7px"><span class="mono gold" style="font-size:12.5px;letter-spacing:.1em;text-transform:uppercase">${r.kind}</span><span class="mono" style="font-size:17px;font-weight:600">${r.name}</span><span style="font-size:15px;line-height:1.45;color:#B4BED2">${r.line}</span></div>`))}`);

const CONTRIBUTE = SECTION('Contribute', 'New guardrails are <span class="gold">content, not code.</span>', `
<p class="sub">A policy is a manifest plus the evals that prove it fires. No engine change and no plugin API to learn.</p>
${grid(2, 16, [['01', 'Add an eval case', 'Found a bypass? Write the case that should have blocked it.'], ['02', 'Verify an agent row', 'Run your agent, capture real payloads, and turn a vendor-docs row into a live-run one.'], ['03', 'Ship a policy', 'chock new policy: a manifest, its tier, and an eval suite. CI checks the claim.'], ['04', 'Add an agent adapter', 'Bring a new coding agent into agentseam. The honesty rule overrides preference.']].map(([n, t, p]) => `<div class="panel" style="padding:24px;display:flex;flex-direction:column;gap:10px"><div style="display:flex;gap:12px;align-items:baseline"><span class="mono gold" style="font-size:14px">${n}</span><span style="font-size:22px;font-weight:600">${t}</span></div><span style="font-size:16.5px;line-height:1.5;color:#B4BED2">${p}</span></div>`))}`);

const HONEST = SECTION('Guardrails, not guarantees', 'And we tell you <span class="gold">which is which.</span>', `
${grid(3, 16, [['commit', 'A git hook or CI gate that exits non-zero.'], ['in-agent', 'The agent\'s own pre-tool hook. Best-effort, and it fails open.'], ['advisory', 'Rule text the agent reads. Nothing stops a refusal to follow it.']].map(([t, p]) => `<div class="panel" style="padding:24px;display:flex;flex-direction:column;gap:12px">${tag(t)}<span style="font-size:17px;line-height:1.5;color:#D5DBE8">${p}</span></div>`))}
${grid(3, 16, [[A.grades.enforced, 'matrix cells graded &ldquo;enforced&rdquo;: no agent reaches it'], [`${D.asi.refused_at_commit.length} of ${D.asi.with_policy}`, 'OWASP Agentic risks with a slice refused at commit'], [D.asi.fully_covered, 'OWASP Agentic risks fully covered: every mapping is partial']].map(([n, l]) => stat(n, l)))}`);

const ALL_NEW = { refusal: REFUSAL, layers: LAYERS, quickstart: QUICKSTART, matrix: MATRIX, catalog: CATALOG, family: FAMILY, contribute: CONTRIBUTE, honest: HONEST };

// 1280x640 social preview banners: the same specs as the covers, laid out for the fixed canvas.
const social = ({ repo, title, sub, chips, right }) => `<div class="social" style="width:1280px;height:640px;padding:64px 72px;background:#222C44;display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:48px;align-items:center;overflow:hidden">
<div style="display:flex;flex-direction:column;gap:24px">
<div style="display:flex;align-items:center;gap:14px">${MARK}<span class="mono" style="font-size:22px;font-weight:600">${repo}</span></div>
<h1 style="font-size:54px">${title}</h1><p class="sub" style="font-size:20px">${sub}</p>
<div style="display:flex;flex-wrap:wrap;gap:10px">${chips.map((c) => `<span class="chip">${c}</span>`).join('')}</div></div>
<div>${right}</div></div>`;
const SOCIALS = Object.fromEntries(SPECS.map((sp) => [`social-${sp.repo === 'open-coder-ai' ? 'org' : sp.repo}`, page(social(sp))]));

const ALL = { ...COVERS, ...ALL_NEW, ...SOCIALS, appsec: APPSEC, adopt: ADOPT, roles: ROLES, compare: COMPARE, pipeline: PIPELINE };
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
const pgPanel = await (await browser.newContext({ deviceScaleFactor: 2 })).newPage();
const pgSocial = await (await browser.newContext({ deviceScaleFactor: 1 })).newPage();
const ONLY = process.env.ONLY ? process.env.ONLY.split(',') : null;
for (const [name, html] of Object.entries(ALL)) {
  if (ONLY && !ONLY.includes(name)) continue;
  const isSocial = name.startsWith('social-');
  const pg = isSocial ? pgSocial : pgPanel;
  await pg.setViewportSize({ width: isSocial ? 1280 : 1200, height: isSocial ? 640 : 800 });
  await pg.setContent(html, { waitUntil: 'networkidle' });
  await pg.evaluate(() => document.fonts.ready);
  await pg.locator(isSocial ? '.social' : '.frame').screenshot({ path: path.join(OUT, `${name}.png`) });
  console.log(`${name}.png`);
}
await browser.close();

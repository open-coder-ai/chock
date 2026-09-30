// Renders the navy/gold README panels for every open-coder-ai repository to PNG.
// Usage: node docs/assets/readme/render.mjs   (needs the `playwright` package and a Chromium;
// set CHROMIUM=/path/to/chrome to use a preinstalled one). Writes docs/assets/readme/*.png.
// Numbers below come from chock-catalog's registry.yaml; edit them here and re-run.
import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const OUT = process.env.OUT_DIR || path.dirname(fileURLToPath(import.meta.url));
const N = { policies: 48, evals: '1,182', java: 129, javaPacks: 16, agentRules: 29, agentPacks: 10, agents: 16 };

const CSS = `
*{box-sizing:border-box}
body{margin:0;background:#0D1626;color:#E8EEF6;font-family:Geist,system-ui,sans-serif}
.mono{font-family:"Geist Mono",ui-monospace,monospace}
.frame{width:1200px;padding:56px 60px;background:#0D1626}
.eyebrow{font-family:"Geist Mono",ui-monospace,monospace;font-size:15px;letter-spacing:.14em;text-transform:uppercase;color:#D9B45C}
h1{margin:0;font-size:52px;line-height:1.05;font-weight:700;letter-spacing:-.03em}
h2{margin:0;font-size:38px;line-height:1.1;font-weight:600;letter-spacing:-.02em}
.gold{color:#D9B45C}
.sub{margin:0;font-size:21px;line-height:1.5;color:#9FB0C4}
.chip{font-family:"Geist Mono",ui-monospace,monospace;font-size:15px;padding:7px 12px;border:1px solid #243452;border-radius:7px;background:#111E33;color:#C9D4E2;white-space:nowrap}
.panel{border:1px solid #243452;border-radius:16px;background:#111E33}
.term{border:1px solid #243452;border-radius:14px;background:#0A1220;padding:24px 26px;font-family:"Geist Mono",ui-monospace,monospace;font-size:16px;line-height:1.75;color:#E8EEF6}
.d{color:#D9B45C}.no{color:#F29B8A}.c{color:#5A6B80}
.tier{font-family:"Geist Mono",ui-monospace,monospace;font-size:12.5px;font-weight:600;padding:3px 8px;border-radius:5px;white-space:nowrap}
.tc{background:#2a78d6;color:#fff}.ta{background:#9ec5f4;color:#0D1626}.td{background:#383835;color:#E8EEF6;border:1px solid #52514e}
`;
const MARK = `<svg width="46" height="46" viewBox="0 0 512 512" aria-hidden="true"><rect width="512" height="512" rx="104" fill="#111E33"/><path d="M 210.1 183.2 L 156.2 256.0 L 210.1 328.8" fill="none" stroke="#D9B45C" stroke-width="24.76" stroke-linecap="round" stroke-linejoin="round"/><path d="M 301.9 183.2 L 355.8 256.0 L 301.9 328.8" fill="none" stroke="#D9B45C" stroke-width="24.76" stroke-linecap="round" stroke-linejoin="round"/><rect x="227.25" y="227.25" width="57.51" height="57.51" transform="rotate(45 256 256)" fill="#D9B45C"/></svg>`;
const page = (body) => `<!doctype html><html lang="en"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>${CSS}</style></head><body>${body}</body></html>`;

const REFUSALS = `<div class="term"><div class="c"># refused at the agent hook and at commit</div>
<div><span class="d">❯</span> git commit -qm repository</div><div class="no">✗ \${} SQL in a MyBatis mapper</div>
<div><span class="d">❯</span> git commit -qm iam</div><div class="no">✗ IAM Action "*" on Resource "*"</div>
<div><span class="d">❯</span> git commit -qm mcp</div><div class="no">✗ MCP server pinned to @latest</div>
<div><span class="d">❯</span> git commit -qm ui</div><div class="no">✗ aria-label stripped from a button</div>
</div>`;

function cover({ repo, title, sub, chips, right }) {
  return page(`<div class="frame" style="display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:48px;align-items:center;padding:64px 60px">
<div style="display:flex;flex-direction:column;gap:26px">
<div style="display:flex;align-items:center;gap:14px">${MARK}<span class="mono" style="font-size:22px;font-weight:600">${repo}</span></div>
<h1>${title}</h1>
<p class="sub">${sub}</p>
<div style="display:flex;flex-wrap:wrap;gap:10px">${chips.map((c) => `<span class="chip">${c}</span>`).join('')}</div>
</div>
<div>${right}</div></div>`);
}
const install = (client, lines, note) => `<div class="term"><div class="c"># ${client}</div>${lines.map((l) => `<div><span class="d">❯</span> ${l}</div>`).join('')}${note ? `<div class="c" style="margin-top:10px">${note}</div>` : ''}</div>`;

const baseChips = [`${N.policies} policies`, `${N.evals} eval cases`, 'OWASP Agentic 10/10', 'Apache-2.0'];
const plugin = (repo, client, lines, note) => cover({
  repo, title: `Application-security guards <span class="gold">for ${client}.</span>`,
  sub: `The Chock catalog packaged as ${client} plugins. Guard plugins judge what the agent is about to run or write, in ${client} itself.`,
  chips: ['14 deny-hook plugins', '12 advisory', 'generated from chock-catalog'], right: install(client, lines, note),
});

const COVERS = {
  'cover-org': cover({ repo: 'open-coder-ai', title: 'Application security <span class="gold">for the code your AI agents write.</span>',
    sub: 'Agents already ask before they run a shell command. We check what they write — at the agent\'s hook, at commit and in CI.', chips: baseChips, right: REFUSALS }),
  'cover-chock': cover({ repo: 'chock', title: 'Application-security policy <span class="gold">as code, for every agent.</span>',
    sub: 'One policy compiles to the agent\'s own hook, a git hook and a CI gate — Claude Code, Cursor, Copilot, Codex, Gemini CLI and more.', chips: baseChips, right: REFUSALS }),
  'cover-chock-catalog': cover({ repo: 'chock-catalog', title: `${N.policies} application-security policies <span class="gold">for AI-written code.</span>`,
    sub: 'Java &amp; Kotlin, agent code, cloud IAM, supply chain, accessibility and the OWASP Agentic Top 10 — each labelled by what it enforces.', chips: [`${N.java} Java rules`, `${N.agentRules} agent-code rules`, `${N.evals} eval cases`, 'OWASP 10/10'], right: REFUSALS }),
  'cover-agentseam': cover({ repo: 'agentseam', title: 'Write an app-sec guard once. <span class="gold">Run it in 16 coding agents.</span>',
    sub: 'One handler API over every agent\'s hooks, instruction files, plugins and config — with an honest matrix of where a guard can block.', chips: ['16 agents', '192 graded cells', 'stdlib-only', 'Apache-2.0'],
    right: `<div class="term"><div><span class="d">def</span> handler(event):</div><div>&nbsp;&nbsp;<span class="d">if</span> unsafe_write(event):</div><div>&nbsp;&nbsp;&nbsp;&nbsp;<span class="d">return</span> Decision.deny(<span style="color:#9ED3A6">"…"</span>)</div><div>&nbsp;&nbsp;<span class="d">return</span> Decision.allow()</div><div style="margin-top:10px"><span class="d">❯</span> agentseam install all "python3 h.py"</div><div class="c">wired into 12 agents · graded honestly</div></div>` }),
  'cover-context-report': cover({ repo: 'context-report', title: 'Signed evidence that an <span class="gold">agent plugin actually works.</span>',
    sub: 'Reachability, fault behaviour, cost and efficacy for plugins, hooks, skills, AGENTS.md and MCP servers — every row re-derivable or claimed.', chips: ['Sigstore · in-toto', 'row-level evidence', 'Apache-2.0'],
    right: `<div class="term"><div class="c"># measured across 18 public plugins</div><div><span class="no">3 of 18</span> reachable but not executable</div><div><span class="no">every</span> running hook allows malformed input</div><div><span class="d">~920 ms</span> p50 for hooks that shell out to npx</div></div>` }),
  'cover-chock-threat-intel': cover({ repo: 'chock-threat-intel', title: 'Every new agentic threat, <span class="gold">answered by a policy.</span>',
    sub: 'A weekly, human-reviewed digest: each MITRE ATLAS and OWASP entry scored enforced, advisory, or policy wanted.', chips: ['weekly', 'MITRE ATLAS', 'OWASP ASI', 'human-reviewed'],
    right: `<div class="term"><div><span class="d">AML.T0051</span> prompt injection</div><div class="c">→ block-invisible-unicode · enforced</div><div><span class="d">AML.T0081</span> modify agent config</div><div class="c">→ protect-agent-config · in-agent</div><div><span class="d">AML.T0118</span> agent-to-agent comms</div><div class="c">→ owasp-asi07 · advisory</div></div>` }),
  'cover-chock-quickstart': cover({ repo: 'chock-quickstart', title: 'Start a repo with app-sec guardrails <span class="gold">in 60 seconds.</span>',
    sub: 'Exactly what chock init leaves behind — then turn on the checks your stack needs.', chips: ['template repo', 'no policies preinstalled'],
    right: install('after "Use this template"', ['chock sync --repo .', 'chock add java-security', 'chock add no-a11y-regression', 'chock sync --repo .'], 'git never clones hooks — sync wires them') }),
  'cover-chock-example': cover({ repo: 'chock-example', title: 'A working Chock adoption, <span class="gold">end to end.</span>',
    sub: 'One policy per layer — git hook, agent rule and skill — small enough to read in one sitting, ready to copy.', chips: ['template repo', 'hook · rule · skill'], right: REFUSALS }),
  'cover-chock-claude-plugins': plugin('chock-claude-plugins', 'Claude Code', ['/plugin marketplace add open-coder-ai/chock-claude-plugins', '/plugin install java-security@chock']),
  'cover-chock-copilot-plugins': plugin('chock-copilot-plugins', 'GitHub Copilot', ['add open-coder-ai/chock-copilot-plugins', '  as a plugin marketplace', 'install a plugin by name'], 'Copilot CLI and VS Code agent mode'),
  'cover-chock-cursor-plugins': plugin('chock-cursor-plugins', 'Cursor', ['Dashboard → Plugins → Add Marketplace', 'Import from Repo:', '  open-coder-ai/chock-cursor-plugins']),
  'cover-chock-codex-plugins': plugin('chock-codex-plugins', 'Codex', ['[marketplaces.chock-codex]  # ~/.codex/config.toml', 'install from the Plugins UI', 'approve each guard\'s hook trust review']),
  'cover-chock-devin-plugins': plugin('chock-devin-plugins', 'Devin', ['devin plugins install open-coder-ai/chock-devin-plugins'], 'Devin hooks are best-effort and fail open, by Devin\'s design'),
};

const card = (n, t, p, pols) => `<div class="panel" style="padding:24px;display:flex;flex-direction:column;gap:12px">
<div style="display:flex;gap:10px;align-items:baseline"><span class="mono gold" style="font-size:14px">${n}</span><span style="font-size:22px;font-weight:600">${t}</span></div>
<div style="font-size:16.5px;line-height:1.5;color:#9FB0C4;flex-grow:1">${p}</div>
<div style="display:flex;flex-wrap:wrap;gap:8px">${pols.map(([id, tier]) => `<span class="mono" style="display:inline-flex;gap:8px;align-items:center;font-size:13.5px;padding:5px 8px;border:1px solid #243452;border-radius:6px;background:#0D1626">${id} <span class="tier ${tier === 'commit' ? 'tc' : tier === 'in-agent' ? 'ta' : 'td'}">${tier}</span></span>`).join('')}</div></div>`;

const APPSEC = page(`<div class="frame" style="display:flex;flex-direction:column;gap:30px">
<div style="display:flex;justify-content:space-between;align-items:flex-end;gap:30px"><div style="display:flex;flex-direction:column;gap:12px"><span class="eyebrow">What it checks</span><h2>Application security first.</h2></div>
<div style="display:flex;gap:10px"><span class="tier tc">commit</span><span class="tier ta">in-agent</span><span class="tier td">advisory</span></div></div>
<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px">
${card('01', 'Java &amp; Kotlin', `${N.java} rules in ${N.javaPacks} packs: injection, XXE, SSRF, deserialization, weak crypto, disabled Spring Security.`, [['java-security', 'commit']])}
${card('02', 'Agent code', `${N.agentRules} rules for LangChain, CrewAI, AutoGen, the OpenAI &amp; Claude Agent SDKs and MCP.`, [['agentic-code-security', 'commit']])}
${card('03', 'Unsafe code &amp; IAM', 'eval, shell=True, os.system, pickle; IAM Action:*, AdministratorAccess, roles/owner.', [['block-unsafe-code-execution', 'commit'], ['block-wildcard-iam', 'commit']])}
${card('04', 'Supply chain', 'Hallucinated packages, Actions on a mutable tag, MCP servers and images at @latest.', [['verify-dependency-exists', 'commit'], ['pin-github-actions', 'commit'], ['block-unpinned-agent-components', 'commit']])}
${card('05', 'OWASP Agentic Top 10', 'A policy for every risk ASI01–ASI10, with enforced slices for ASI03, 04 and 05.', [['owasp-asi01…10', 'advisory']])}
${card('06', 'Accessibility', 'ADA · Section 508 · WCAG: a change that strips an alt, aria-label, label or lang is refused.', [['no-a11y-regression', 'commit']])}
${card('07', 'Memory &amp; prompt injection', 'Secrets and pasted history in agent memory; bidi overrides and hidden Unicode instructions.', [['guard-memory-writes', 'commit'], ['block-invisible-unicode', 'commit']])}
${card('08', 'Test integrity', 'Deleted tests, net assertion loss, assert True, new skip / .only / @Disabled.', [['protect-test-integrity', 'commit'], ['block-test-skips', 'commit']])}
${card('09', 'Also included', 'Secrets, destructive commands and hook bypass, agent self-protection, EU AI Act.', [['scan-secrets', 'commit'], ['block-destructive-commands', 'commit'], ['protect-agent-config', 'in-agent']])}
</div></div>`);

const ADOPT = page(`<div class="frame" style="display:flex;flex-direction:column;gap:30px">
<div style="display:flex;flex-direction:column;gap:12px"><span class="eyebrow">Get started</span><h2>Adopt it two ways.</h2></div>
<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px">
<div class="panel" style="padding:30px;display:flex;flex-direction:column;gap:18px;border-color:#33466A">
<div style="display:flex;justify-content:space-between;align-items:center"><span class="eyebrow">Route 1</span><span class="mono" style="font-size:13px;padding:5px 10px;border-radius:999px;background:#D9B45C;color:#0D1626">for teams</span></div>
<div style="font-size:28px;font-weight:600">In your repository, with Chock</div>
<div class="term" style="font-size:15.5px"><div><span class="d">❯</span> pip install chock</div><div><span class="d">❯</span> chock init .</div><div><span class="d">❯</span> chock add java-security</div><div><span class="d">❯</span> chock sync --repo .</div><div><span class="d">❯</span> chock sync --ci <span class="c"># same gate in CI</span></div></div>
<div style="font-size:17px;line-height:1.55;color:#C9D4E2">Every developer and every agent on the repo. Checked at the agent's hook, at commit and in CI. Travels with every clone.</div></div>
<div class="panel" style="padding:30px;display:flex;flex-direction:column;gap:18px">
<div style="display:flex;justify-content:space-between;align-items:center"><span class="eyebrow">Route 2</span><span class="mono" style="font-size:13px;padding:5px 10px;border-radius:999px;border:1px solid #33466A;color:#C9D4E2">no repo changes</span></div>
<div style="font-size:28px;font-weight:600">In your coding agent, as plugins</div>
<div class="term" style="font-size:13.5px;line-height:1.55;display:grid;grid-template-columns:104px minmax(0,1fr);gap:10px 12px"><span class="d">Claude Code</span><span>/plugin marketplace add<br>open-coder-ai/chock-claude-plugins</span><span class="d">Copilot</span><span>marketplace:<br>open-coder-ai/chock-copilot-plugins</span><span class="d">Cursor</span><span>Plugins → Import from Repo:<br>open-coder-ai/chock-cursor-plugins</span><span class="d">Codex</span><span>[marketplaces.chock-codex]<br>in ~/.codex/config.toml</span><span class="d">Devin</span><span>devin plugins install<br>open-coder-ai/chock-devin-plugins</span></div>
<div style="font-size:17px;line-height:1.55;color:#C9D4E2">Your own sessions in that client, today. Best-effort pre-tool hooks; pair with route 1 for commit and CI.</div></div>
</div></div>`);

const role = (t, s, lines) => `<div class="panel" style="padding:26px;display:flex;flex-direction:column;gap:12px">
<div style="font-size:23px;font-weight:600">${t}</div><div class="mono" style="font-size:13.5px;color:#9FB0C4">${s}</div>
${lines.map(([k, v]) => `<div style="display:grid;grid-template-columns:96px minmax(0,1fr);gap:12px;padding-top:10px;border-top:1px solid #1F3050;font-size:16px;line-height:1.5;color:#C9D4E2"><span class="mono gold" style="font-size:12.5px;letter-spacing:.06em;text-transform:uppercase;padding-top:3px">${k}</span><span>${v}</span></div>`).join('')}</div>`;
const ROLES = page(`<div class="frame" style="display:flex;flex-direction:column;gap:30px">
<div style="display:flex;flex-direction:column;gap:12px"><span class="eyebrow">A normal day, by role</span><h2>What changes for the people who ship with agents.</h2></div>
<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px">
${role('Java &amp; Kotlin developers', 'Spring · Jakarta · Quarkus · Micronaut · Android', [['Agent', 'puts ${id} into a MyBatis query'], ['Chock', 'refuses it at the agent hook and at commit, naming the rule'], ['You get', `${N.java} rules as the code is written — allow · deny · ask per pack`]])}
${role('Web &amp; UX designers', 'ADA · Section 508 · WCAG', [['Agent', 'empties an alt or drops an aria-label in a refactor'], ['Chock', 'refuses the change and names the element'], ['You get', 'accessibility fixes that can\'t quietly regress']])}
${role('Agent memory', 'CLAUDE.md · MEMORY.md · the agent\'s own stores', [['Agent', 'writes a pasted diff or an API key into memory'], ['Chock', 'refuses it — including stores outside the repo'], ['You get', 'memory that stays small, true and secret-free']])}
${role('AppSec &amp; OWASP owners', 'OWASP Top 10 for Agentic Applications', [['Today', 'a checklist in a wiki, followed or not'], ['Chock', 'a policy for every ASI01–ASI10 risk, in the repo'], ['You get', 'a review checklist that runs on every commit']])}
${role('Threat modeling', 'MITRE ATLAS', [['Maps', '11 ATLAS techniques to named policies'], ['Weekly', 'every new entry scored enforced, advisory or policy wanted'], ['You get', 'from technique ID to the control that answers it']])}
${role('Platform &amp; governance', 'Policy as code, with an audit trail', [['Chock', 'one policy → agent hook, git hook and CI gate'], ['Pinned', 'hash-pinned installs in chock.lock'], ['You get', 'a coverage grade per policy × agent, with evidence']])}
</div></div>`);

const row = (k, a, b) => `<div style="display:grid;grid-template-columns:190px minmax(0,1fr) minmax(0,1.25fr);gap:24px;padding:18px 26px;border-top:1px solid #1F3050;font-size:17px;line-height:1.5"><span style="font-weight:600;color:#C9D4E2">${k}</span><span style="color:#9FB0C4">${a}</span><span>${b}</span></div>`;
const COMPARE = page(`<div class="frame" style="display:flex;flex-direction:column;gap:30px">
<div style="display:flex;flex-direction:column;gap:12px"><span class="eyebrow">More than a blocklist</span><h2>Your agent already asks before rm -rf. <span class="gold">That was never the hard part.</span></h2></div>
<div class="panel" style="overflow:hidden;background:#0F1B2E">
<div style="display:grid;grid-template-columns:190px minmax(0,1fr) minmax(0,1.25fr);gap:24px;padding:16px 26px;background:#15243D" class="mono"><span></span><span style="font-size:13px;letter-spacing:.1em;color:#9FB0C4">AGENT DEFAULTS</span><span class="gold" style="font-size:13px;letter-spacing:.1em">WITH CHOCK</span></div>
${row('What it knows', 'Generic "allow this command?" prompts', `Your stack — ${N.java} Java rules, accessibility, IAM, MCP, memory`)}
${row('Where it lives', 'One person\'s settings, in one tool', 'Files in the repo, reviewed in pull requests')}
${row('Which agents', 'Each agent, its own format and gaps', 'One policy for Claude Code, Cursor, Copilot, Codex and more')}
${row('After the agent', 'Nothing at commit or in CI', 'The same rule as a git hook and a CI gate')}
${row('When it says no', 'A prompt the developer clicks through', 'A refusal that names the fix — the agent corrects itself')}
${row('Proof', 'Trust the vendor', `${N.evals} eval cases replayed in CI, a coverage grade per agent`)}
</div></div>`);

const ALL = { ...COVERS, 'appsec': APPSEC, 'adopt': ADOPT, 'roles': ROLES, 'compare': COMPARE };
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
const pg = await browser.newPage({ viewport: { width: 1200, height: 800 }, deviceScaleFactor: 2 });
for (const [name, html] of Object.entries(ALL)) {
  await pg.setContent(html, { waitUntil: 'networkidle' });
  await pg.evaluate(() => document.fonts.ready);
  await pg.locator('.frame').screenshot({ path: path.join(OUT, `${name}.png`) });
  console.log(`${name}.png`);
}
await browser.close();

// Renders one incident overlay to PNG: node docs/assets/readme/render-incident.mjs <slug> [out.png] [--compact for the 4:5 version]   (needs `playwright`; CHROMIUM=/path to use a preinstalled Chromium)
import { chromium } from 'playwright';
import { mkdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { incident, compact } from './incident-overlay.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2), small = args.includes('--compact'), [slug, out = path.join(HERE, 'v2', 'incidents', `${slug}${small ? '-compact' : ''}.png`)] = args.filter((a) => a !== '--compact');
const read = (...p) => JSON.parse(readFileSync(path.join(HERE, ...p), 'utf8'));
const CSS = `*{box-sizing:border-box}body{margin:0;background:#FBF7EE;font-family:"Instrument Sans",system-ui,sans-serif;font-weight:500}.mono{font-family:"JetBrains Mono",ui-monospace,monospace}.eyebrow{font-family:"JetBrains Mono",ui-monospace,monospace;letter-spacing:.14em;text-transform:uppercase}`;
const page = (body) => `<!doctype html><html lang="en"><head><meta charset="utf-8"><link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400..700&family=JetBrains+Mono:wght@400..700&display=swap" rel="stylesheet"><style>${CSS}</style></head><body>${body}</body></html>`;
const html = (small ? compact : incident)(page, read('where-chock-sits.json'), read('incidents', `${slug}.json`));
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args: ['--no-sandbox'] });
const pg = await (await browser.newContext({ deviceScaleFactor: 2 })).newPage();
await pg.setViewportSize({ width: small ? 1080 : 880, height: small ? 1350 : 800 });
await pg.setContent(html, { waitUntil: 'networkidle' });
const ok = await pg.evaluate(async () => {
  const fonts = ['16px "Instrument Sans"', '600 16px "Instrument Sans"', '14px "JetBrains Mono"'];
  await Promise.all(fonts.map((f) => document.fonts.load(f)));
  return fonts.map((f) => document.fonts.check(f));
});
if (!ok.every(Boolean)) throw new Error(`fonts missing (Instrument Sans / JetBrains Mono): ${ok}`);
mkdirSync(path.dirname(out), { recursive: true });
await pg.locator('#incident').screenshot({ path: out });
await browser.close();
console.log(out);

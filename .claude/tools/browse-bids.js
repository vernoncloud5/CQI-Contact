// browse-bids.js: read PUBLIC bid listing pages that need JavaScript, using the installed headless Chromium.
// Rules built in: honors robots.txt (skips Disallowed paths), never logs in, never solves CAPTCHA or bot checks,
// stops on a challenge page. Usage: node browse-bids.js '<json [[name,url],...]>' [outdir]
const { chromium } = require('playwright');
const fs = require('fs');
const URLS = JSON.parse(process.argv[2]);
const OUT = process.argv[3] || '.';
const KW = /janitor|custodial|housekeep|landscap|grounds|mowing|lawn|trash|refuse|waste|recycl|dumpster|laundry|linen|courier|security guard|staffing|towing|pressure wash|power wash|pest|shred|flooring|carpet|plumbing|graffiti|septic|snow/i;
const CHALLENGE = /just a moment|verify you are human|captcha|access denied|attention required|web page blocked|bot check|browser check|pardon our interruption/i;
async function allowed(u) {
  const p = new URL(u);
  try {
    const r = await fetch(p.origin + '/robots.txt', { headers: { 'User-Agent': 'Mozilla/5.0' }, signal: AbortSignal.timeout(20000) });
    if (!r.ok) return [true, ''];
    const t = await r.text(); let star = false; const dis = [], al = [];
    for (const line of t.split(/\r?\n/)) {
      const l = line.split('#')[0].trim(); const m = l.match(/^([A-Za-z-]+)\s*:\s*(.*)$/); if (!m) continue;
      const k = m[1].toLowerCase(), v = m[2].trim();
      if (k === 'user-agent') star = (v === '*'); else if (star && k === 'disallow' && v) dis.push(v); else if (star && k === 'allow' && v) al.push(v);
    }
    const rx = x => new RegExp('^' + x.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\\\$$/, '$'));
    const path = p.pathname + p.search;
    const d = dis.filter(x => rx(x).test(path)).sort((a, b) => b.length - a.length)[0];
    const a = al.filter(x => rx(x).test(path)).sort((a, b) => b.length - a.length)[0];
    return d && !(a && a.length >= d.length) ? [false, 'Disallow ' + d] : [true, ''];
  } catch (e) { return [true, '']; }
}
(async () => {
  const b = await chromium.launch();
  for (const [name, u] of URLS) {
    const [ok, note] = await allowed(u);
    if (!ok) { console.log(`## ${name}\n  ROBOTS DISALLOWS (${note}), not fetched`); continue; }
    try {
      const pg = await b.newPage();
      await pg.goto(u, { timeout: 45000, waitUntil: 'networkidle' }).catch(() => {});
      for (const t of ['Close', 'Dismiss', 'No thanks', 'Continue as guest', 'Accept', 'Got it']) {
        try { const l = pg.getByRole('button', { name: t }); if (await l.count()) await l.first().click({ timeout: 1500 }); } catch (e) {}
      }
      const txt = await pg.innerText('body');
      if (!txt.trim() || (txt.length < 400 && CHALLENGE.test(txt))) { console.log(`## ${name}\n  NO CONTENT or bot/blocked page (len ${txt.length}), stopped, not bypassed`); await pg.close(); continue; }
      fs.writeFileSync(`${OUT}/${name.replace(/\W+/g, '_')}.txt`, txt);
      const hits = txt.split('\n').map(s => s.trim()).filter(s => s && KW.test(s));
      console.log(`## ${name}: OK, ${txt.length} chars, ${hits.length} keyword lines`);
      hits.slice(0, 14).forEach(h => console.log('  - ' + h.slice(0, 200)));
      await pg.close();
    } catch (e) { console.log(`## ${name}\n  ERR ${String(e).slice(0, 90)}`); }
  }
  await b.close();
})();

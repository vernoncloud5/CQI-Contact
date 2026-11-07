#!/usr/bin/env node
// Fills and submits a vendor's website "Contact Us" form with Vernon's quote request.
// Usage:
//   node .claude/tools/submit-form.mjs <url> <message-file> [--company "Vendor Name"] [--dry-run]
// Rules (from Vernon's playbook): only plain contact/quote forms. Stops on CAPTCHA,
// logins, payment fields or sign-ups. Never retries around a CAPTCHA.
// Prints one JSON line: {status, url, fieldsFilled, reason, screenshot}.

import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const CQI = {
  firstName: 'Vernon',
  lastName: 'Cloud',
  fullName: 'Vernon Cloud',
  company: 'Cloud Quantum Innovations',
  email: 'vernon@cloudquantuminnovations.com',
  phone: '210-802-1984',
  city: 'San Antonio',
  state: 'TX',
  zip: '78247',
};

const args = process.argv.slice(2);
const url = args[0];
const msgFile = args[1];
const dryRun = args.includes('--dry-run');
const ci = args.indexOf('--company');
const vendor = ci > -1 ? args[ci + 1] : '';

function out(obj) {
  console.log(JSON.stringify({ url, vendor, ...obj }));
}

if (!url || !msgFile || !fs.existsSync(msgFile)) {
  out({ status: 'error', reason: 'usage: submit-form.mjs <url> <message-file> [--company name] [--dry-run]' });
  process.exit(2);
}
const message = fs.readFileSync(msgFile, 'utf8').trim();
const subjectLine = (message.match(/^Subject:\s*(.+)$/m) || [])[1] || 'Estimate Request';
const body = message.replace(/^Subject:.*\n+/m, '');

const shotDir = path.join(process.cwd(), '.claude', 'tools', 'form-shots');
fs.mkdirSync(shotDir, { recursive: true });
const shot = path.join(shotDir, `${(vendor || new URL(url).hostname).replace(/[^a-z0-9]+/gi, '_')}_${Date.now()}.png`);

const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1280, height: 1600 } })).newPage();
try {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(2500);

  // Hard stops: CAPTCHA, login, payment.
  const html = (await page.content()).toLowerCase();
  if (/g-recaptcha|recaptcha\/api|hcaptcha|cf-turnstile|challenges\.cloudflare/.test(html)) {
    await page.screenshot({ path: shot, fullPage: true });
    out({ status: 'skipped', reason: 'captcha', screenshot: shot });
    process.exit(0);
  }
  if (await page.locator('input[type=password], input[autocomplete="cc-number"]').count()) {
    out({ status: 'skipped', reason: 'login or payment field present' });
    process.exit(0);
  }

  // Pick the form with a textarea (the message box).
  const forms = page.locator('form:has(textarea)');
  if (!(await forms.count())) {
    out({ status: 'skipped', reason: 'no contact form with a message box found' });
    process.exit(0);
  }
  const form = forms.first();

  const fields = await form.locator('input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=checkbox]):not([type=radio]), textarea, select').all();
  let filled = [];
  for (const el of fields) {
    if (!(await el.isVisible())) continue;
    const meta = (await el.evaluate((n) => {
      const lab = n.id ? document.querySelector(`label[for="${n.id}"]`) : null;
      return [n.name, n.id, n.placeholder, n.getAttribute('aria-label'), n.type, lab ? lab.innerText : '', n.closest('label') ? n.closest('label').innerText : ''].join(' ');
    })).toLowerCase();
    const tag = await el.evaluate((n) => n.tagName.toLowerCase());
    let val = null;
    if (tag === 'textarea' || /message|comment|question|details|inquiry|how can we help|description/.test(meta)) val = body;
    else if (/e-?mail/.test(meta)) val = CQI.email;
    else if (/phone|tel|mobile/.test(meta)) val = CQI.phone;
    else if (/first/.test(meta)) val = CQI.firstName;
    else if (/last|surname/.test(meta)) val = CQI.lastName;
    else if (/company|business|organi[sz]ation/.test(meta)) val = CQI.company;
    else if (/subject|topic|regarding/.test(meta)) val = subjectLine;
    else if (/name/.test(meta)) val = CQI.fullName;
    else if (/city/.test(meta)) val = CQI.city;
    else if (/state/.test(meta) && tag !== 'select') val = CQI.state;
    else if (/zip|postal/.test(meta)) val = CQI.zip;
    if (val === null) continue;
    if (tag === 'select') continue;
    await el.fill(val);
    filled.push(meta.trim().split(/\s+/).slice(0, 3).join(' '));
  }
  if (!filled.some((f) => f) || !(await form.locator('textarea').first().inputValue())) {
    out({ status: 'skipped', reason: 'could not identify message field', fieldsFilled: filled });
    process.exit(0);
  }
  // Leave required selects/checkboxes alone; if any required field is still empty, stop.
  const emptyRequired = await form.locator('[required]').evaluateAll((els) => els.filter((e) => e.offsetParent !== null && !e.value && e.type !== 'checkbox').length);
  if (emptyRequired) {
    await page.screenshot({ path: shot, fullPage: true });
    out({ status: 'skipped', reason: `${emptyRequired} required field(s) not understood`, fieldsFilled: filled, screenshot: shot });
    process.exit(0);
  }

  if (dryRun) {
    await page.screenshot({ path: shot, fullPage: true });
    out({ status: 'dry-run', fieldsFilled: filled, screenshot: shot });
    process.exit(0);
  }

  const submit = form.locator('button[type=submit], input[type=submit], button:not([type])').first();
  await submit.click({ timeout: 10000 });
  await page.waitForTimeout(4000);
  const after = (await page.innerText('body')).toLowerCase();
  await page.screenshot({ path: shot, fullPage: true });
  const ok = /thank|received|we.ll be in touch|message has been sent|submitted|success/.test(after);
  out({ status: ok ? 'submitted' : 'submitted-unconfirmed', fieldsFilled: filled, screenshot: shot });
} catch (e) {
  out({ status: 'error', reason: String(e.message || e).slice(0, 200) });
} finally {
  await browser.close();
}

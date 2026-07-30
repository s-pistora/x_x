/**
 * Snímky aplikace pro prezentaci.
 *
 * Server běží na self-signed certifikátu, proto ignoreHTTPSErrors — jinak by
 * Chromium spojení odmítl stejně jako telefon před potvrzením certifikátu.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, 'snimky');
const BASE = 'https://localhost:5050';
const PIN = process.env.ADMIN_PIN;

mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ args: ['--force-color-profile=srgb', '--hide-scrollbars'] });

async function stranka({ theme = 'dark', width = 1600, height = 1000 } = {}) {
  const ctx = await browser.newContext({
    viewport: { width, height }, deviceScaleFactor: 2,
    locale: 'cs-CZ', timezoneId: 'Europe/Prague',
    colorScheme: theme, reducedMotion: 'reduce', ignoreHTTPSErrors: true,
  });
  const page = await ctx.newPage();
  await page.addInitScript((t) => localStorage.setItem('ept_theme', t), theme);
  return { ctx, page };
}

async function prihlas(page) {
  const r = await page.request.post(`${BASE}/api/login`, {
    data: { role: 'admin', pin: PIN }, ignoreHTTPSErrors: true,
  });
  const { token } = await r.json();
  await page.addInitScript((t) => {
    sessionStorage.setItem('ept_token', t);
    sessionStorage.setItem('ept_role', 'admin');
  }, token);
}

async function snap(name, opts, akce) {
  const { ctx, page } = await stranka(opts);
  if (opts?.auth !== false) await prihlas(page);
  await page.goto(BASE + (opts?.url || '/'), { waitUntil: 'networkidle' });
  await page.waitForFunction(
    () => !document.querySelector('#tbl')?.textContent.includes('Načítám'),
    { timeout: 8000 },
  ).catch(() => {});
  if (akce) await akce(page);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(OUT, `${name}.png`), animations: 'disabled', caret: 'hide' });
  console.log('  ✓', name);
  await ctx.close();
}

await snap('dashboard-dark', {});
await snap('dashboard-light', { theme: 'light' });
await snap('lock', { auth: false });
await snap('qr-panel', {}, async (p) => {
  await p.locator('#qrCard').scrollIntoViewIfNeeded();
});
await snap('audit', {}, async (p) => {
  await p.getByRole('button', { name: 'Audit' }).click();
  await p.waitForSelector('#auditModal:not(.hidden)');
  await p.waitForTimeout(600);
});
await snap('sken-mobil', { url: '/sken', width: 390, height: 844, auth: false });

// Výřez QR panelu zvlášť — v decku se hodí detail, ne celá obrazovka
{
  const { ctx, page } = await stranka({});
  await prihlas(page);
  await page.goto(BASE + '/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  await page.locator('#qrCard').screenshot({ path: join(OUT, 'qr-detail.png') });
  console.log('  ✓ qr-detail');
  await ctx.close();
}

// Evakuační seznam v tiskovém režimu — emulace print media, aby se v decku
// ukázalo přesně to, co vyleze z tiskárny
{
  const { ctx, page } = await stranka({ theme: 'light', width: 1240, height: 1600 });
  await prihlas(page);
  await page.goto(BASE + '/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  await page.evaluate(async () => {
    const res = await fetch('/api/navstevnici?filter=aktivni', {
      headers: { 'X-Auth-Token': sessionStorage.getItem('ept_token') },
    });
    const lidi = await res.json();
    document.getElementById('evakCas').textContent =
      'Stav k ' + new Date().toLocaleString('cs-CZ') + ' — celkem ' + lidi.length + ' osob v budově';
    document.getElementById('evakTbody').innerHTML = lidi.map(r => `<tr>
        <td><strong>${r.jmeno} ${r.prijmeni}</strong></td>
        <td>${r.organizace || '—'}</td><td>${r.spz || '—'}</td>
        <td>${r.prichod_dt.slice(11, 16)}</td><td class="evak-podpis"></td></tr>`).join('');
    document.body.classList.add('tisk-evakuace');
  });
  await page.emulateMedia({ media: 'print' });
  await page.waitForTimeout(300);
  await page.screenshot({ path: join(OUT, 'evakuace.png') });
  console.log('  ✓ evakuace');
  await ctx.close();
}

await browser.close();
console.log(`\nsnímky v ${OUT}`);

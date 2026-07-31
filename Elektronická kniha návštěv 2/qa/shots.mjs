/**
 * Vizuální QA harness — projede každý stav aplikace a uloží snímek.
 *
 * Determinismus:
 *  - `clock.setFixedTime` zmrazí Date (tikající hodiny, živý čítač doby), ale NECHÁ
 *    běžet setTimeout — ten aplikace potřebuje (300ms debounce hledání, focus PINu).
 *    `clock.install()/pauseAt()` by tohle rozbilo.
 *  - `window.setInterval` se vyřadí, aby uprostřed snímku nepřekreslil tabulku.
 *  - Kamera jede na statickém canvas streamu (nativní fake device je animovaný
 *    s časovým razítkem = nedeterministický).
 *  - `/api/ocr` a POST `/api/navstevnici` se mockují — OCR na tomhle stroji stejně
 *    nefunguje (chybí tesseract) a reálný POST by špinil seed.
 */
import { chromium } from 'playwright';
import { readFileSync, mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const QA = dirname(fileURLToPath(import.meta.url));
const OUT = join(QA, 'shots');
const BASE = 'http://localhost:5050';

const manifest = JSON.parse(readFileSync(join(QA, 'seed-manifest.json'), 'utf8'));
const REF = new Date(manifest.reference_epoch_ms);

const VP = {
  desktop: { width: 1440, height: 900, deviceScaleFactor: 2 },
  wide:    { width: 1920, height: 1080, deviceScaleFactor: 1 },
  tablet:  { width: 768,  height: 1024, deviceScaleFactor: 2 },
  mobile:  { width: 390,  height: 844,  deviceScaleFactor: 2 },
};

let TOKEN = null;
let browser;
const done = [];

async function login() {
  const r = await fetch(`${BASE}/api/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role: 'admin', pin: 'ept-admin-2026' }),
  });
  TOKEN = (await r.json()).token;
}

async function shot(name, opts = {}) {
  const {
    url = '/', viewport = 'desktop', theme = 'dark', auth = true,
    setup = null, fullPage = false, cameraFail = false,
    ocr = { jmeno: 'Tereza', prijmeni: 'Novotná' }, ocrDelay = 0, ocrFail = false,
  } = opts;

  const { deviceScaleFactor, ...size } = VP[viewport];
  const ctx = await browser.newContext({
    viewport: size, deviceScaleFactor,
    locale: 'cs-CZ', timezoneId: 'Europe/Prague',
    colorScheme: theme, reducedMotion: 'reduce', permissions: ['camera'],
  });
  const page = await ctx.newPage();

  await page.clock.setFixedTime(REF);

  await page.addInitScript(({ theme, token, cameraFail }) => {
    localStorage.setItem('ept_theme', theme);
    if (token) {
      sessionStorage.setItem('ept_token', token);
      sessionStorage.setItem('ept_role', 'admin');
    }
    // Vyřadit jen setInterval (hodiny, čítač doby, auto-refresh).
    // setTimeout musí zůstat — debounce hledání a focus PIN pole na něm stojí.
    window.setInterval = () => 0;

    // Statická „občanka" místo animovaného testovacího obrazce.
    const karta = () => {
      const c = document.createElement('canvas');
      c.width = 1280; c.height = 960;
      const g = c.getContext('2d');
      g.fillStyle = '#0f141b'; g.fillRect(0, 0, 1280, 960);
      g.fillStyle = '#e8e2d4'; g.fillRect(150, 210, 980, 560);
      g.fillStyle = '#a70a1b'; g.fillRect(150, 210, 980, 62);
      g.fillStyle = '#fff'; g.font = 'bold 30px sans-serif';
      g.fillText('ČESKÁ REPUBLIKA — OBČANSKÝ PRŮKAZ', 178, 252);
      g.fillStyle = '#c9c2b2'; g.fillRect(190, 320, 210, 270);
      g.fillStyle = '#4a4a4a'; g.font = '22px sans-serif';
      g.fillText('FOTO', 258, 460);
      g.fillStyle = '#5b6470'; g.font = '20px sans-serif';
      g.fillText('Příjmení / Surname', 450, 360);
      g.fillText('Jméno / Given names', 450, 460);
      g.fillText('Datum narození', 450, 560);
      g.fillStyle = '#141d28'; g.font = 'bold 34px sans-serif';
      g.fillText('NOVOTNÁ', 450, 400);
      g.fillText('TEREZA', 450, 500);
      g.fillText('14. 03. 1988', 450, 600);
      return c;
    };
    navigator.mediaDevices.getUserMedia = async () => {
      if (cameraFail) {
        const e = new Error('Requested device not found.');
        e.name = 'NotFoundError';
        throw e;
      }
      return karta().captureStream(5);
    };
  }, { theme, token: auth ? TOKEN : null, cameraFail });

  // OCR na tomhle stroji nefunguje (není tesseract) — mock drží flow realistický.
  await page.route('**/api/ocr', async (route) => {
    if (ocrDelay) await new Promise((r) => setTimeout(r, ocrDelay));
    if (ocrFail) return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: 'OCR selhalo' }) });
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ text: 'PŘÍJMENÍ NOVOTNÁ JMÉNO TEREZA', ...ocr }),
    });
  });
  // Zápis návštěvníka nesmí špinit seed → statistiky by se rozjely mezi běhy.
  await page.route('**/api/navstevnici', async (route, req) => {
    if (req.method() !== 'POST') return route.fallback();
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ status: 'ok', id: 999, prichod_dt: manifest.reference_time.replace('T', ' ') }),
    });
  });

  await page.goto(BASE + url, { waitUntil: 'networkidle' });

  if (auth && url === '/') {
    await page.waitForFunction(
      () => !document.querySelector('#tbl')?.textContent.includes('Načítám'),
      { timeout: 8000 },
    ).catch(() => {});
  }

  if (setup) await setup(page);

  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(150);

  await page.screenshot({
    path: join(OUT, `${name}.png`),
    fullPage, animations: 'disabled', caret: 'hide', scale: 'css',
  });
  done.push(name);
  console.log('  ✓', name);
  await ctx.close();
}

// ── pomocníci ──────────────────────────────────────────────────────────────
const tab = (label) => async (page) => {
  await page.locator('.tab', { hasText: new RegExp(`^${label}$`) }).click();
  await page.waitForTimeout(500);
};
const alertF = (type, msg) => async (page) =>
  page.evaluate(([type, msg]) => showAlert('fAlert', type, msg), [type, msg]);

// projde skenem až na daný krok reálným klikáním
const skenDo = (krok) => async (page) => {
  await page.getByRole('button', { name: 'Spustit kameru' }).click();
  await page.waitForFunction(() => document.getElementById('vidEl').videoWidth > 0, { timeout: 8000 });
  if (krok === 1) return;
  await page.getByRole('button', { name: 'Vyfotit doklad' }).click();
  if (krok === 2) { await page.waitForSelector('#step2:not(.hidden)'); return; }
  await page.waitForSelector('#step3:not(.hidden)', { timeout: 8000 });
};

async function main() {
  rmSync(OUT, { recursive: true, force: true });
  mkdirSync(OUT, { recursive: true });
  await login();
  browser = await chromium.launch({
    args: [
      '--force-color-profile=srgb',
      '--disable-lcd-text',
      '--font-render-hinting=none',
      '--hide-scrollbars',
      '--use-fake-ui-for-media-stream',
    ],
  });

  console.log('RECEPCE — přihlašovací obrazovka');
  await shot('01-lock-dark-desktop',  { auth: false });
  await shot('02-lock-light-desktop', { auth: false, theme: 'light' });
  await shot('03-lock-dark-mobile',   { auth: false, viewport: 'mobile' });
  await shot('04-lock-dark-tablet',   { auth: false, viewport: 'tablet' });

  console.log('RECEPCE — přihlašovací modal');
  await shot('05-login-admin-dark', {
    auth: false, setup: async (p) => {
      await p.getByRole('button', { name: 'Přihlásit se jako admin' }).click();
      await p.waitForSelector('#loginModal:not(.hidden)');
    },
  });
  await shot('06-login-spravce-light', {
    auth: false, theme: 'light', setup: async (p) => {
      await p.getByRole('button', { name: 'Přihlásit se jako správce' }).click();
      await p.waitForSelector('#loginModal:not(.hidden)');
    },
  });
  await shot('07-login-chyba-dark', {
    auth: false, setup: async (p) => {
      await p.getByRole('button', { name: 'Přihlásit se jako admin' }).click();
      await p.fill('#loginPin', 'spatneheslo');
      await p.locator('#btnLogin').click();
      await p.waitForSelector('#loginAlert:not(.hidden)');
    },
  });

  console.log('RECEPCE — dashboard');
  await shot('08-dash-pritomni-dark-desktop',  {});
  await shot('09-dash-pritomni-light-desktop', { theme: 'light' });
  await shot('10-dash-pritomni-dark-wide',     { viewport: 'wide' });
  await shot('11-dash-pritomni-dark-tablet',   { viewport: 'tablet' });
  await shot('12-dash-pritomni-dark-mobile',   { viewport: 'mobile' });
  await shot('13-dash-pritomni-light-mobile',  { theme: 'light', viewport: 'mobile' });
  await shot('14-dash-dnes-dark',      { setup: tab('Dnes') });
  // tab „Historie" zrušen — vracel bajt po bajtu totéž co „Vše“ (backend pro něj
  // neměl vlastní větev, filtr propadl bez omezení)
  await shot('16-dash-vse-dark',       { setup: tab('Vše') });
  await shot('17-dash-vse-light',      { theme: 'light', setup: tab('Vše') });
  await shot('18-dash-vse-fullpage',   { setup: tab('Vše'), fullPage: true });

  console.log('RECEPCE — hledání');
  await shot('19-hledat-prazdne-dark', { setup: tab('Hledat') });
  await shot('20-hledat-vysledky-dark', {
    setup: async (p) => { await tab('Hledat')(p); await p.fill('#qText', 'Nov'); await p.waitForTimeout(800); },
  });
  await shot('21-hledat-bez-vysledku-dark', {
    setup: async (p) => { await tab('Hledat')(p); await p.fill('#qText', 'Zzz'); await p.waitForTimeout(800); },
  });
  await shot('22-hledat-datum-light', {
    theme: 'light',
    setup: async (p) => {
      await tab('Hledat')(p);
      await p.fill('#qDD', '30'); await p.fill('#qMM', '07'); await p.fill('#qYYYY', '2026');
      await p.waitForTimeout(800);
    },
  });

  console.log('RECEPCE — modaly (jen viewport, jsou to fixed overlaye)');
  await shot('23-modal-upravit-dark', {
    setup: async (p) => { await p.getByRole('button', { name: 'Upravit' }).first().click(); await p.waitForSelector('#modal:not(.hidden)'); },
  });
  await shot('24-modal-upravit-light', {
    theme: 'light',
    setup: async (p) => { await p.getByRole('button', { name: 'Upravit' }).first().click(); await p.waitForSelector('#modal:not(.hidden)'); },
  });
  await shot('25-modal-odchod-dark', {
    setup: async (p) => { await p.getByRole('button', { name: 'Odejít' }).first().click(); await p.waitForSelector('#confirmModal:not(.hidden)'); },
  });
  await shot('26-modal-odchod-mobile', {
    viewport: 'mobile',
    setup: async (p) => { await p.getByRole('button', { name: 'Odejít' }).first().click(); await p.waitForSelector('#confirmModal:not(.hidden)'); },
  });

  console.log('RECEPCE — hlášky');
  await shot('27-alert-success-dark', {
    setup: async (p) => {
      await p.fill('#fJmeno', 'Tereza'); await p.fill('#fPrijmeni', 'Novotná');
      await p.fill('#fOrg', 'Siemens s.r.o.'); await p.fill('#fSpz', '4AB 1234');
      await p.locator('#btnZapis').click();
      await p.waitForSelector('#fAlert.alert-success');
    },
  });
  await shot('28-alert-success-light', {
    theme: 'light', setup: alertF('success', '✓ Tereza Novotná zapsán/a v 14:30.'),
  });
  await shot('29-alert-error-dark', {
    setup: async (p) => { await p.locator('#btnZapis').click(); await p.waitForSelector('#fAlert.alert-error'); },
  });
  await shot('30-alert-info-dark',   { setup: alertF('info',  '⏳ Zpracovávám doklad…') });
  await shot('31-alert-amber-dark',  { setup: alertF('amber', '⚠ Jméno se nepodařilo rozpoznat – doplňte ručně.') });
  await shot('32-alert-amber-light', { theme: 'light', setup: alertF('amber', '⚠ Jméno se nepodařilo rozpoznat – doplňte ručně.') });

  console.log('RECEPCE — webkamera');
  await shot('33-webkamera-dark', {
    setup: async (p) => {
      await p.getByRole('button', { name: 'Použít webkameru' }).click();
      await p.waitForFunction(() => document.getElementById('video').videoWidth > 0, { timeout: 8000 });
      await p.waitForTimeout(300);
    },
  });

  console.log('SKEN — mobilní flow');
  const sken = { url: '/sken', viewport: 'mobile', auth: false };
  await shot('34-sken-krok1-dark-mobile',  { ...sken });
  await shot('35-sken-krok1-light-mobile', { ...sken, theme: 'light' });
  await shot('36-sken-krok1-dark-tablet',  { ...sken, viewport: 'tablet' });
  await shot('37-sken-kamera-bezi',        { ...sken, setup: skenDo(1) });
  await shot('38-sken-krok2-rozpoznavani', { ...sken, ocrDelay: 4000, setup: skenDo(2) });
  await shot('39-sken-krok3-rozpoznano-dark',  { ...sken, setup: skenDo(3) });
  await shot('40-sken-krok3-rozpoznano-light', { ...sken, theme: 'light', setup: skenDo(3) });
  await shot('41-sken-krok3-nerozpoznano', {
    ...sken, ocr: { jmeno: '', prijmeni: '' }, setup: skenDo(3),
  });
  await shot('42-sken-krok3-chyba-ocr', { ...sken, ocrFail: true, setup: skenDo(3) });
  await shot('43-sken-hotovo-dark', {
    ...sken, setup: async (p) => {
      await skenDo(3)(p);
      await p.locator('#btnZapis').click();
      await p.waitForSelector('#successScreen:not(.hidden)');
    },
  });
  await shot('44-sken-hotovo-light', {
    ...sken, theme: 'light', setup: async (p) => {
      await skenDo(3)(p);
      await p.locator('#btnZapis').click();
      await p.waitForSelector('#successScreen:not(.hidden)');
    },
  });
  await shot('45-sken-chyba-kamery', {
    ...sken, cameraFail: true, setup: async (p) => {
      await p.getByRole('button', { name: 'Spustit kameru' }).click();
      await p.waitForSelector('#camErr:not(.hidden)');
    },
  });

  await browser.close();
  console.log(`\nHOTOVO — ${done.length} snímků v ${OUT}`);
}

main().catch(async (e) => {
  console.error('CHYBA:', e.message);
  if (browser) await browser.close();
  process.exit(1);
});

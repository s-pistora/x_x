/**
 * Snímky skutečného skenovacího toku pro prezentaci.
 *
 * Na rozdíl od QA harnessu tady OCR NENÍ mockované — kamera dostane vzorový
 * doklad jako statický stream a projde se celá pipeline (série snímků → řazení
 * podle ostrosti → čtení). Co je na obrázcích, to server opravdu udělal.
 */
import { chromium } from 'playwright';
import { readFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, 'snimky');
mkdirSync(OUT, { recursive: true });

const doklad = readFileSync(join(OUT, 'doklad-ostry.png')).toString('base64');
const browser = await chromium.launch({ args: ['--hide-scrollbars', '--force-color-profile=srgb'] });

const ctx = await browser.newContext({
  viewport: { width: 400, height: 860 }, deviceScaleFactor: 3,
  locale: 'cs-CZ', timezoneId: 'Europe/Prague', colorScheme: 'dark',
  reducedMotion: 'reduce', permissions: ['camera'], ignoreHTTPSErrors: true,
});
const page = await ctx.newPage();

// Kamera vrací vzorový doklad jako statický stream — deterministické a bez
// nutnosti mít u stroje fyzickou kartu.
await page.addInitScript((b64) => {
  localStorage.setItem('ept_theme', 'dark');
  const img = new Image();
  img.src = 'data:image/png;base64,' + b64;
  navigator.mediaDevices.getUserMedia = async () => {
    const c = document.createElement('canvas');
    c.width = 1280; c.height = 960;
    const g = c.getContext('2d');
    const kresli = () => {
      g.fillStyle = '#10151c'; g.fillRect(0, 0, c.width, c.height);
      if (img.complete && img.naturalWidth) {
        const m = Math.min(c.width * .92 / img.naturalWidth, c.height * .82 / img.naturalHeight);
        const w = img.naturalWidth * m, h = img.naturalHeight * m;
        g.drawImage(img, (c.width - w) / 2, (c.height - h) / 2, w, h);
      }
      requestAnimationFrame(kresli);
    };
    kresli();
    return c.captureStream(10);
  };
}, doklad);

async function snap(name) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(200);
  await page.screenshot({ path: join(OUT, `${name}.png`), animations: 'disabled', caret: 'hide' });
  console.log('  ✓', name);
}

await page.goto('https://localhost:5050/sken', { waitUntil: 'networkidle' });
await snap('ocr-1-start');

await page.getByRole('button', { name: 'Spustit kameru' }).click();
await page.waitForFunction(() => document.getElementById('vidEl').videoWidth > 0, { timeout: 15000 });
await page.waitForTimeout(600);
await snap('ocr-2-kamera');

// Spustí sérii 30 snímků a následné čtení. Necháme doběhnout.
await page.getByRole('button', { name: 'Vyfotit doklad' }).click();
await page.waitForTimeout(2600);
await snap('ocr-3-sbirani');

await page.waitForSelector('#step3:not(.hidden)', { timeout: 120000 });
await page.waitForTimeout(700);
await snap('ocr-4-vysledek');

const vyplneno = await page.evaluate(() => ({
  jmeno: document.getElementById('rJmeno').value,
  prijmeni: document.getElementById('rPrijmeni').value,
}));
console.log('  formulář vyplněn:', JSON.stringify(vyplneno));

await browser.close();

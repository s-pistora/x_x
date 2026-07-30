/**
 * Vyrenderuje deck.html do PDF.
 *
 * Přes Playwright/Chromium, protože ten už na stroji je (používá ho QA harness)
 * a umí přesně to, co potřebujeme: A4 na šířku, tisk pozadí a fonty z base64.
 * Žádná další závislost jako wkhtmltopdf.
 */
import { chromium } from 'playwright';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const VSTUP = pathToFileURL(join(HERE, 'deck.html')).href;
const VYSTUP = join(HERE, 'Digitalni-kniha-navstev-EPT.pdf');

const browser = await chromium.launch();
const page = await browser.newPage();

// Chyby v konzoli by znamenaly nenačtený obrázek nebo font — chceme o nich vědět,
// ne je objevit až v hotovém PDF.
const problemy = [];
page.on('requestfailed', (r) => problemy.push(`nenačteno: ${r.url().split('/').pop()}`));
page.on('pageerror', (e) => problemy.push(`chyba stránky: ${e.message}`));

await page.goto(VSTUP, { waitUntil: 'networkidle' });
await page.evaluate(() => document.fonts.ready);
await page.waitForTimeout(400);

// Kontrola, že se fonty EPT skutečně použily. Bez nich by PDF vypadalo obyčejně
// a přišlo by o značkový charakter, aniž by to cokoliv nahlásilo.
const fonty = await page.evaluate(() => ({
  cairo: document.fonts.check('700 20px Cairo'),
  inter: document.fonts.check('400 12px Inter'),
  stran: document.querySelectorAll('.s').length,
}));

await page.pdf({
  path: VYSTUP,
  format: 'A4',
  landscape: true,
  printBackground: true,
  preferCSSPageSize: false,
  margin: { top: '0', right: '0', bottom: '0', left: '0' },
});

await browser.close();

console.log(`slidů v HTML:   ${fonty.stran}`);
console.log(`font Cairo:     ${fonty.cairo ? 'ano' : 'NE — deck by nebyl značkový'}`);
console.log(`font Inter:     ${fonty.inter ? 'ano' : 'NE'}`);
if (problemy.length) {
  console.log('\nPROBLÉMY:');
  for (const p of new Set(problemy)) console.log('  !', p);
} else {
  console.log('bez chyb — všechny obrázky a fonty se načetly');
}
console.log(`\nPDF: ${VYSTUP}`);

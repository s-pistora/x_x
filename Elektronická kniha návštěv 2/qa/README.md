# Vizuální QA harness

Deterministické snímky každé obrazovky a stavu aplikace + strukturovaný design review.
Slouží k regresnímu testování vzhledu: po zásahu do `recepce.html`, `sken.html`
nebo `static/ept-theme.css` se přeřízne sada snímků a porovná se s předchozí.

## Spuštění

```bash
npm i playwright && npx playwright install chromium
python3 qa/seed.py          # naplní DB reprezentativními daty + zapíše seed-manifest.json
python3 backend_v2.py       # musí běžet na http://localhost:5050
node qa/shots.mjs           # 45 snímků do qa/shots/
node qa/measure.mjs         # změří rytmus mezer a velikost dotykových cílů
```

## Na co si dát pozor

`shots.mjs` zmrazuje hodiny prohlížeče na `reference_epoch_ms` ze `seed-manifest.json`.
Ten vztah se nesmí rozpojit — sloupec „Doba" se počítá jako `new Date() − prichod_dt`,
takže při zmrazení na čas nesouvisející se seed daty ukáže nuly nebo absurdní hodnoty
a review to nahlásí jako chybu designu, i když jde o chybu harnessu. Když se přeseeduje,
musí se přeříznout i snímky.

Zmrazuje se `clock.setFixedTime`, ne `clock.install()/pauseAt()` — `setTimeout` musí dál
běžet, stojí na něm debounce hledání a fokus PIN pole. Vyřazuje se jen `setInterval`
(tikající hodiny, živý čítač doby, auto-refresh).

OCR a POST `/api/navstevnici` jsou mockované: OCR na vývojovém stroji není (chybí
tesseract) a reálný zápis by špinil seed. Kamera jede na statickém canvas streamu,
protože nativní fake device je animovaný, tedy nedeterministický.

## Výsledky review

`findings-round1.json` … `findings-round3.json` — jeden nezávislý agent na jeden snímek,
strukturované nálezy se `severity`. Pozor: recenzent generuje i falešné nálezy
(subjektivní soudy, chybně přečtený text, placeholder zaměněný za hodnotu, domněnky
o kontrastu). Nálezy je nutné před opravou ověřit proti kódu nebo výpočtem, ne
aplikovat plošně — v prvním kole bylo z 6 „critical" nálezů reálných 2,5.

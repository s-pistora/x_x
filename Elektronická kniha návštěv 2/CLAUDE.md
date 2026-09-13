# Návštěvní kniha v2 — popis aplikace pro Claude Code

> Obsah tohoto souboru je záměrně totožný s [`AGENT.md`](./AGENT.md) —
> `AGENT.md` je obecný popis pro libovolného AI agenta/nástroj,
> `CLAUDE.md` je stejný obsah čtený automaticky Claude Code. Při úpravě
> jednoho aktualizuj i druhý.

Tento soubor popisuje kompletní funkčnost aplikace, aby se v ní uměl
zorientovat i agent, který v ní ještě nikdy nepracoval — zejména proto,
aby mohl bezpečně upravovat frontend (`recepce.html`, `sken.html`) a
znal přesný tvar API, na kterém frontend stojí.

## Co aplikace dělá

Digitální kniha návštěv pro recepci (aktuálně nasazeno pro **Habartov**).
Návštěvník u vstupu vyfotí telefonem občanský průkaz, AI OCR z něj
přečte jméno a příjmení, návštěvník/recepční to potvrdí a zapíše se
příchod. Fotka dokladu se **nikdy neukládá** — z ní se jen jednorázově
vytáhne text. Při odchodu recepční zapíše odchod ručně (tlačítko
v dashboardu). Aplikace dál umí přehled aktivních návštěv, hledání v
historii, audit log, export do CSV a tiskový evakuační seznam osob v
budově.

## Architektura

```
┌───────────────┐        QR / URL        ┌───────────────┐
│  recepce.html │◄──────────────────────►│   sken.html   │
│  (dashboard,  │   otevře se na          │  (mobilní     │
│  notebook/    │   telefonu návštěvníka  │  self-service │
│  tablet)      │                         │  sken)        │
└───────┬───────┘                         └───────┬───────┘
        │              fetch('/api/...')          │
        └───────────────────┬──────────────────────┘
                             ▼
                     ┌───────────────┐
                     │ backend_v2.py │  Flask + REST JSON API
                     │  (app)        │  statická obsluha HTML
                     └───┬───────┬───┘
                         │       │
             ┌───────────┘       └───────────┐
             ▼                                ▼
    ┌─────────────────┐              ┌──────────────────┐
    │ ocr_processor.py │              │   db_manager.py   │
    │ EasyOCR (hlavní) │              │  SQLite (soubor   │
    │ + Tesseract      │              │ navstevni_kniha.db│
    │ (záloha)         │              │  navstevnici +    │
    └─────────────────┘              │  audit_log)        │
                                      └──────────────────┘
                             │
                             ▼
                     ┌────────────────┐
                     │ sms_notifier.py │  mock / Twilio SMS
                     └────────────────┘

Před backendem (jen pro demo/produkci s HTTPS):
  tls_proxy.py  — TLS na :5050 → přeposílá na Flask na 127.0.0.1:5051
  (nutné, protože prohlížeč pustí kameru getUserMedia jen na https/localhost)
```

## Adresářová struktura

- `backend_v2.py` — Flask aplikace, všechny REST endpointy, servíruje i
  statické HTML (`/` → `recepce.html`, `/sken` → `sken.html`).
- `db_manager.py` — databázová vrstva nad SQLite (`navstevni_kniha.db`),
  logika zápisu příchodu/odchodu, audit log, normalizace jmen
  (porovnání bez diakritiky/velikosti písmen).
- `ocr_processor.py` — rozpoznání textu z fotky dokladu (EasyOCR →
  fallback Tesseract) a extrakce jména/příjmení podle rozvržení české
  občanky; whitelist známých osob pro testovací provoz.
- `sms_notifier.py` — validace telefonu, odeslání SMS (mock do konzole,
  nebo ostrá Twilio integrace) s rate-limitem (cooldown).
- `email_notifier.py` — e-mail hostiteli při odbavení na iPad kiosku (mock
  do konzole, nebo ostrá Resend integrace přes jejich REST API).
- `tls_proxy.py` — jednoduché TLS zakončení ze standardní knihovny
  (přelévá bajty do Flasku na localhostu), protože Flaskův dev server
  se s `ssl_context` ukázal nespolehlivý.
- `run_produkcne.py` — produkční start pod WSGI serverem `waitress`
  (místo Flaskova dev serveru).
- `recepce.html` — hlavní frontend: dashboard recepce (desktop/tablet).
- `sken.html` — mobilní frontend: krokový self-service sken dokladu.
- `ipad.html` — kiosek pro iPad na vstupu (náhrada recepce): sken dokladu →
  organizace → výběr osoby, za kterou se jde → zápis příchodu, samoobslužně
  ve smyčce (bez přihlášení). Viz sekce „iPad kiosek" níže.
- `kontakty.json` — seznam osob k výběru v kroku „za kým jdete" na iPad
  kiosku (aktuálně fiktivní data; nahradí se skutečným seznamem od firmy).
  Pole `email` (nepovinné, prázdné = neposílá se nic) — na něj jde
  notifikace přes `email_notifier.py`, když si návštěvník tuhle osobu
  vybere. Nikdy se neposílá do frontendu, viz `GET /api/kontakty`.
- `static/` — loga a CSS (`ept-theme.css`, `ept-fonts.css`) sdílené
  frontendy.
- `nastav_https.sh` — vygeneruje self-signed TLS certifikát pro
  aktuální LAN IP (nutné pro `subjectAltName`, jinak ho prohlížeče
  odmítnou).
- `start_demo.sh` — spustí appku (port 5051) + TLS proxy (port 5050)
  jedním příkazem, včetně kontroly a případné regenerace certifikátu
  při změně IP.
- `qa/` — QA skripty (demo data, seed dat, vizuální snímky stránek,
  zápisy zjištění z kontrol).
- `DEMO.md` — postup a scénář pro živé demo na prezentaci.
- `README_v2.md` — stručný instalační návod.
- `.env` / `.env.example` — konfigurace (PINy, SMS, porty, OCR režim).
- `navstevni_kniha.db` — SQLite databázový soubor (vzniká automaticky).
- `one-pager.html` — marketingová prezentace produktu (samostatná, mimo appku).

## Spuštění

### Vývoj / demo (HTTPS, kvůli kameře na telefonu)
```bash
cd "Elektronická kniha návštěv 2"
./nastav_https.sh      # vygeneruje cert pro aktuální LAN IP (jen jednou / po změně sítě)
./start_demo.sh        # spustí backend (5051) + TLS proxy (5050)
```
- Recepce: `https://localhost:5050/`
- Sken z telefonu: `https://<LAN-IP>:5050/sken` (telefon musí být ve
  stejné Wi-Fi; jinak `ngrok http 8080` nebo obdoba)
- Telefon musí při prvním otevření odkliknout varování o certifikátu
  (Pokročilé → Pokračovat), jinak se kamera nespustí.
- Záložní plán bez telefonu: sken jde i na notebooku na
  `https://localhost:5050/sken` — `localhost` je bezpečný původ, kamera
  jede i bez potvrzení certifikátu.

### Jen backend na plain HTTP (bez kamery na telefonu)
```bash
python3 backend_v2.py     # http://localhost:5050 (port lze přepsat PORT=)
```

### Produkce (waitress, za reverzní proxy typu nginx/Caddy, která řeší TLS)
```bash
python3 run_produkcne.py
```

### Závislosti
```bash
pip install -r requirements_v2.txt
```
Klíčové: `flask`, `flask-cors`, `pillow`, `numpy`, `python-dotenv`,
`easyocr` (hlavní OCR engine), `pytesseract` + `opencv-python-headless`
(záloha a oříznutí karty na fotce). `twilio` je odkomentovat jen když
se zapojuje ostré SMS odesílání.

## Proměnné prostředí (`.env`, viz `.env.example`)

| Proměnná | Výchozí | Význam |
|---|---|---|
| `ADMIN_PIN` | `ept-admin-2026` | PIN pro roli admin |
| `SPRAVCE_PIN` | `ept-spravce-2026` | PIN pro roli správce |
| `PORT` | `5050` (`5051` pod `start_demo.sh`) | port, na kterém poslouchá Flask aplikace |
| `EPT_PUBLIC_PORT` | — | veřejný port (za TLS proxy), používá se pro výpis adresy při startu |
| `EPT_HTTPS` | — | `1` = adresy se vypisují jako `https://` (QR/log), appka samotná TLS neřeší |
| `OCR_STRICT_WHITELIST` | `1` | `1` = OCR přizná jméno jen známým lidem z `ZNAMI_LIDE`, jinak vrátí prázdno; `0` = obecná extrakce z libovolného dokladu |
| `EPT_OCR_DEBUG` | — | `1` = uloží fotky + přečtený text do `debug_ocr/` pro ladění extrakce |
| `SMS_ENABLED` | `false` | `false` = SMS jen do konzole (mock); `true` = ostré odeslání přes Twilio |
| `SMS_COOLDOWN_SECONDS` | `10` | minimální rozestup mezi dvěma SMS na stejné číslo |
| `TWILIO_ACCOUNT_SID/AUTH_TOKEN/FROM_NUMBER` | — | přihlašovací údaje Twilio (jen když `SMS_ENABLED=true`) |

## Datový tok skenu (hlavní flow aplikace)

1. Recepce zobrazí QR kód → návštěvník ho naskenuje telefonem.
2. Otevře se `sken.html` → návštěvník vyfotí doklad kamerou (nebo
   nahraje fotku ze zařízení).
3. Fotka (base64) jde na `POST /api/ocr` → `ocr_processor.precti_doklad()`
   → vrátí se `jmeno`, `prijmeni`, přečtený `text` a použitý `engine`.
   **Fotka se nikam neukládá.**
4. Zobrazí se potvrzovací obrazovka s předvyplněným jménem/příjmením
   (+ volitelně organizace, SPZ, telefon) → návštěvník potvrdí.
5. `POST /api/navstevnici` zapíše příchod do databáze. Pokud je osoba
   právě teď v budově (aktivní návštěva), vrátí se `409` s hláškou
   „je již přítomen/a od …“ — druhý aktivní řádek se nezakládá. Pokud
   osoba měla dřívější uzavřenou návštěvu, založí se nový řádek a
   frontend zobrazí „Vítejte zpět“ s datem poslední návštěvy.
6. Volitelně se odešle potvrzovací SMS (pokud návštěvník zadal telefon).
7. Při odchodu recepční v `recepce.html` klikne na záznam → „Zapsat
   odchod“ → `PATCH /api/navstevnici/<id>` s `{"odchod": true}`.

## Backend REST API (`backend_v2.py`)

Base path: `/api`. Frontend volá **relativní** cestu `/api/...` (ne
absolutní `http://localhost:...`) — nutné, aby to fungovalo přes LAN IP,
https i localhost bez mixed-content chyb a bez toho, aby telefon volal
sám sebe.

| Endpoint | Metoda | Auth | Popis |
|---|---|---|---|
| `/` | GET | — | vrátí `recepce.html` |
| `/sken` | GET | — | vrátí `sken.html` |
| `/ipad` | GET | — | vrátí `ipad.html` (kiosek na vstupu) |
| `/api/login` | POST | — | `{role: "admin"\|"spravce", pin}` → `{token, role}` nebo `401` |
| `/api/logout` | POST | token | zruší token |
| `/api/ocr` | POST | — (bez přihlášení, používá i sken-kiosek) | `{image: "<base64>"}` → `{text, jmeno, prijmeni, engine}` |
| `/api/kontakty` | GET | — (bez přihlášení, používá iPad kiosek) | seznam osob pro krok „za kým jdete" — čte se z `kontakty.json` |
| `/api/navstevnici` | POST | — (otevřené, zapisuje i recepce, sken-kiosek i iPad kiosek) | `{jmeno, prijmeni, organizace?, spz?, phone_number?, navstiva_koho?}` → zápis příchodu; `409` při duplicitě aktivní návštěvy |
| `/api/odchod` | POST | — (otevřené, jen iPad kiosek) | `{jmeno, prijmeni}` → dohledá aktivní návštěvu a zapíše odchod; `404` bez shody |
| `/api/navstevnici` | GET | admin/správce | seznam s filtrováním: `filter=aktivni\|dnes\|vse\|hledat`, `q` (jméno/příjmení), `datum`, `hodina_od`, `hodina_do` |
| `/api/navstevnici/<id>` | PATCH | admin/správce | `{odchod: true}` zapíše odchod; nebo `{organizace?, spz?, phone_number?}` upraví záznam |
| `/api/stats` | GET | jakýkoli přihlášený | `{aktivni, dnes, celkem}` |
| `/api/audit` | GET | admin/správce | `?limit=` (max 500) — historie akcí (nový návštěvník, opakovaná návštěva, pokus o duplicitu, zapsán odchod, změna telefonu, selhání OCR) |
| `/api/export.csv` | GET | admin/správce | CSV (středníkem oddělené, BOM pro Excel) všech návštěv |

Autentizace: token se posílá v hlavičce `X-Auth-Token`. Tokeny žijí
**jen v paměti procesu** (dict `TOKENS`) — po restartu serveru je nutné
se přihlásit znovu. Obě role (`admin`, `spravce`) mají identická práva
(plný přístup ke všem záznamům a hledání) — nejde o odstupňovaná
oprávnění, jen o dva sdílené PINy. Řadoví zaměstnanci se nikam
nepřihlašují, jen skenují doklad přes `/sken` bez účtu.

## Databázové schéma (SQLite, `navstevni_kniha.db`)

```sql
CREATE TABLE navstevnici (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    jmeno        TEXT NOT NULL,
    prijmeni     TEXT NOT NULL,
    organizace   TEXT DEFAULT '',
    spz          TEXT DEFAULT '',
    phone_number TEXT DEFAULT '',
    navstiva_koho TEXT DEFAULT '',  -- za kým jde (jen z iPad kiosku, viz ipad.html)
    prichod_dt   TEXT NOT NULL,     -- 'YYYY-MM-DD HH:MM:SS'
    odchod_dt    TEXT               -- NULL = návštěvník je stále v budově
);

CREATE TABLE audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    navstevnik_id INTEGER,
    action        TEXT NOT NULL,    -- novy_navstevnik / opakovana_navsteva /
                                     -- jiz_prihlasen / odchod_zapsan /
                                     -- telefon_zmenen / ocr_selhani
    timestamp     TEXT NOT NULL,
    details       TEXT DEFAULT ''
);
```

Kniha záměrně loguje **každou návštěvu jako samostatný řádek** (historie
docházky), ne jeden řádek na osobu. Duplicitě se předchází jen v jednom
případě: osoba je *právě teď* aktivní (nemá `odchod_dt`) — pak se druhý
aktivní řádek nezaloží. Porovnání jmen pro účely duplicit/„vítejte zpět“
ignoruje diakritiku a velikost písmen (`strip_diakritiku`), ale ukládá
se vždy přesně to, co bylo zadáno/rozpoznáno.

## OCR modul (`ocr_processor.py`)

- **Hlavní engine: EasyOCR** — lokální neuronová síť (offline, zdarma),
  čte čeština+angličtina, běží na CPU s 1 vláknem (kvůli konfliktu
  torch vláken s vláknovým webserverem — jinak se server umí zaseknout
  bez chyby/logu). Model se načítá líně při prvním skenu (~3–17 s podle
  toho, jestli je v cache).
- **Záloha: Tesseract** (`pytesseract`) — použije se, když EasyOCR není
  nainstalované nebo nic nevrátí (typicky iPad/iSH bez PyTorche). Prochází
  STEJNÝM zpracováním jako EasyOCR (`_tesseract_boxy`): oříznutí karty,
  zvětšení, navíc binarizace (`_pripravit_pro_tesseract`, adaptivní práh
  přes OpenCV — Tesseract je na členité pozadí občanky mnohem citlivější
  než neuronka) a `image_to_data` pro souřadnice slov, takže jede přes
  stejnou cílenou extrakci (`_jmeno_prijmeni_z_boxu`) jako EasyOCR, ne
  přes slabší celotextovou extrakci `extrahuj_jmeno`. Ta zůstává jako
  úplně poslední záchrana, jen když se ani boxy nepodaří získat.
- **Oříznutí karty** (`_orizni_kartu`, přes OpenCV): najde v širší fotce
  obdélník s poměrem stran občanky (~1.585), narovná perspektivu a
  zvětší — zásadně zlepšuje čitelnost fotek z telefonu z dálky. Sdílené
  oběma enginy.
- **Cílená extrakce** (`_jmeno_prijmeni_z_boxu`): hledá pole
  PŘÍJMENÍ/SURNAME a JMÉNO/GIVEN NAMES fuzzy porovnáním (kvůli OCR
  překlepům v popiscích), **jen v okně** mezi koncem hlavičky dokladu a
  začátkem dalších údajů (datum narození, pohlaví...). Mimo toto okno
  se jméno nikdy nehledá. Bez jistého popisku v okně vrátí **prázdno**
  — záměrně nehádá, aby se nezapsalo špatné jméno. Otestováno na
  syntetických dokladech i s Tesseractem: za dobrých podmínek (i s
  náklonem/rozostřením/nerovnoměrným pozadím) čte stejně přesně jako
  EasyOCR a je řádově rychlejší. Za fakt špatných podmínek (odlesk +
  stín + velký náklon) oba enginy degradují, ale Tesseract v tom testu
  bezpečně vrátil prázdno (popisky nešly rozpoznat), zatímco EasyOCR
  jednou vrátilo sebejisté, ale ŠPATNÉ jméno — mechanismus prázdna tedy
  funguje jako pojistka u obou enginů, ne jen jako teorie.
- **Evropský průkaz zdravotního pojištění (EHIC)** — jiné rozvržení než
  občanka (popisek NAD hodnotou, ne vlevo od ní; číslovaná pole 3
  Příjmení, 4 Jméno...). Rozpozná se podle hlavičky karty
  (`_je_zdravotni_karta`, `_HLAVICKA_ZDRAVOTKY` — POZOR: bez slova
  "PRŮKAZ", to je na OBOU typech dokladu, takže by nerozlišilo nic).
  `_jmeno_prijmeni_zdravotka` využívá pevné pořadí polí dané EU šablonou
  (Jméno je vždy o 2 řádky pod Příjmení), takže funguje i když se popisek
  „4 Jméno" samotný OCR nepozná (reálně pozorováno: „uco", skóre jistoty
  jen 0.25 — příliš rozbité na fuzzy match, ale pořadí polí drží).
  Ověřeno na reálné fotce (Evropský průkaz zdravotního pojištění).
- **Whitelist známých osob** (`ZNAMI_LIDE`, `uroci_znamou_osobu`):
  testovací provoz je omezen jen na vybrané lidi (aktuálně Simon
  Pistora, William Varga) — stačí čitelné jméno NEBO příjmení kdekoli v
  textu (fuzzy) a zapíše se kanonická hodnota ze seznamu. Přidání
  člověka = přidání řádku do `ZNAMI_LIDE`. Vypnutelné přes
  `OCR_STRICT_WHITELIST=0`, pak se použije obecná extrakce nad
  libovolným dokladem (nedoporučeno na produkčním demu).
  Bezpečnostní pojistka: nestačí vysoký SOUČET podobnosti jména a
  příjmení — reálně chyceno, že cizí doklad (zdravotní karta Ernesta
  Pešty) omylem prošel jako Simon Pistora, protože náhodný šum dal
  jedno vysoké skóre (PEŠTA~PISTORA 0.67) a jedno nízké (šum~SIMON
  0.60), součet 1.27 nad tehdejším prahem 1.1. Od teď se navíc
  vyžaduje, aby i HORŠÍ z dvojice skóre bylo aspoň 0.7 (skutečné shody
  mají obě skóre 0.80–1.00, viz debug_ocr fotky) — jinak hrozí přiřazení
  cizí identity, což je horší než prázdné pole.
- Zamykáno globálním `_ocr_lock` — rozpoznávání nikdy neběží dvakrát
  zaráz (EasyOCR/torch není vláknově bezpečné).

## Frontend

### `recepce.html` — dashboard recepce (desktop/tablet)
Jedna stránka, vanilla JS (žádný framework), volá `/api/...` relativně.
Hlavní části (podle `id` v HTML):
- **Přihlašovací zámek** (`lockScreen`) — dokud není token v
  `sessionStorage`, dashboard je skrytý a zobrazí se výběr role
  admin/správce → PIN.
- **Statistiky** (`s-aktivni`, `s-dnes`, `s-celkem`) — z `/api/stats`.
- **Formulář nového návštěvníka** — ruční zadání jméno/příjmení/
  organizace/SPZ/telefon, nebo foto přes webkameru (`toggleWebcam`,
  `takeSnapshot`) či nahraný soubor (`handleFileSelect`) →
  `zpracujDoklad()` volá `POST /api/ocr` a předvyplní pole.
  Zápis přes `zapsat()` → `POST /api/navstevnici`.
- **Přehled návštěv** — tabulka (`tbl`) s taby `aktivni` / `dnes` /
  `vse`, fulltextové hledání jméno/příjmení + filtr podle data a
  rozsahu hodin (`hledatDebounced`, segmentované vstupy DD/MM/RRRR,
  HH/MM).
- **Modální úprava záznamu** (`modal`) — úprava organizace/SPZ/telefonu,
  tlačítko „Zapsat odchod“ → `PATCH /api/navstevnici/<id>`.
- **Audit log** (`auditModal`) — historie akcí z `/api/audit`.
- **Export** — odkaz/tlačítko na `/api/export.csv`.
- **Evakuační/tiskový seznam** (`#evakuace`, jen pro tisk) — seznam
  aktuálně přítomných osob se sloupcem na podpis.
- Přepínač světlý/tmavý režim (`toggleTheme`, uloženo v `localStorage`).

### `sken.html` — mobilní self-service sken (bez přihlášení)
Krokový průvodce (`step1` → `step2` → `step3`):
1. **Krok 1** — spuštění kamery (`spustKameru`, `getUserMedia` s
   `facingMode: environment`) a focení (`udelFoto`), nebo nahrání
   souboru ze zařízení (`nacistSoubor`).
2. **Krok 2** — odeslání fotky na `POST /api/ocr` (`ocrSnimek` /
   `zpracovatObrazek`), zobrazí se náhled a stav rozpoznávání.
3. **Krok 3** — potvrzovací formulář s předvyplněným jménem/příjmením
   (+ organizace, SPZ, telefon nepovinně) → `zapsat()` volá
   `POST /api/navstevnici`. Při úspěchu se zobrazí `successScreen`
   s potvrzením zápisu.
- Kamera vyžaduje zabezpečený původ (https, nebo `localhost`) — proto
  celý TLS setup (`nastav_https.sh`, `tls_proxy.py`).

### `ipad.html` — vstupní kiosek (náhrada recepce, bez přihlášení)
Jeden iPad stojí místo recepce u vstupu a jede v nekonečné smyčce, jeden
návštěvník po druhém, bez účtu (stejně jako `sken.html`). Krokový průvodce:
1. **Úvod** (`screenIdle`) — klepnutím se zahájí odbavení a spustí kamera.
2. **Doklad** (`screenScan` → `screenName`) — stejná technika jako
   `sken.html` (série snímků, výběr nejostřejšího, `POST /api/ocr`), jen s
   méně snímky (kiosek stojí pevně blíž k dokladu). Selže-li kamera nebo OCR,
   je vždy k dispozici „Zadat jméno ručně".
3. **Firma** (`screenOrg`) — návštěvník doplní organizaci (nepovinné,
   jde přeskočit).
4. **Za kým jdete** (`screenHost`) — mřížka osob z `GET /api/kontakty`
   (`kontakty.json`), s vyhledáváním bez diakritiky; klepnutím na kartu se
   rovnou pokračuje dál. **Seznam je zatím fiktivní** — až firma pošle
   skutečný seznam zaměstnanců, stačí ho naimportovat do `kontakty.json`
   (žádná změna API/frontendu).
5. **Shrnutí** (`screenFinal`) — `POST /api/navstevnici` s
   `navstiva_koho` navíc oproti `sken.html`. `409 jiz_prihlasen` se
   zobrazí jako informace, ne jako chyba.
6. **Úspěch** (`screenSuccess`) — potvrzení a automatický návrat na krok 1
   po 8 s (nebo tlačítkem hned) — kiosek je tak připravený na dalšího
   návštěvníka bez zásahu obsluhy.
- **Samoobslužný odchod** — tlačítko „Odcházím – odepsat se" na úvodní
  obrazovce (`zahajitOdchod()`) spustí STEJNOU obrazovku skenu/potvrzení
  jména (`rezimOdchodu = true`), ale po potvrzení jména se místo firmy/
  hostitele rovnou zavolá `POST /api/odchod` (`zapsatOdchod()`) — appka
  dohledá AKTIVNÍ návštěvu podle jména (`db.najdi_aktivni_navstevu`,
  fuzzy na diakritiku/velikost písmen) a zapíše `odchod_dt`. Bez shody
  (jiné jméno, nebo osoba už odešla) vrátí `404` s chybovou hláškou,
  appka to ukáže jako alert a nechá zkusit znovu. Úspěšná obrazovka
  ukáže, kolik minut/hodin byla osoba v budově.
- Nepoužívá přepínač světlý/tmavý režim ani `localStorage` z recepce —
  veřejná obrazovka vždy jede ve světlém režimu bez ohledu na to, co má
  recepce nastavené pro sebe.
- **Zaseknutí skenu**: `udelFoto()` je celá obalená try/catch/finally a
  `fetch` na `/api/ocr` má 15s timeout (`AbortController`) — appka se
  nikdy nezasekne natrvalo na "Snímám/Rozpoznávám doklad…" bez možnosti
  pokračovat, i kdyby OCR na serveru selhalo nebo se zaseklo (viz
  poznámka o torch/EasyOCR threading rizicích u `backend_v2.py` výš).

### Sdílené statické zdroje (`static/`)
`ept-theme.css`, `ept-fonts.css` a loga (`ept_logo.*`, `praut_logo.*`)
— použitá v obou HTML stránkách i v `one-pager.html`/`docs/index.html`.

## SMS notifikace (`sms_notifier.py`)
- Validace telefonu: přijme `+420xxxxxxxxx` nebo 9 číslic, normalizuje
  na `+420xxxxxxxxx`; jinak vrátí `None` (API vrátí `400`).
- Bez `SMS_ENABLED=true` se SMS jen vypíše do konzole/logu (mock, bez
  nutnosti Twilio účtu) — bezpečný výchozí stav pro vývoj.
- Rate limiting (`cooldown`): mezi dvěma SMS na stejné číslo musí
  uplynout `SMS_COOLDOWN_SECONDS` (výchozí 10 s), jinak se SMS jen
  přeskočí (`status: "cooldown"`), stav žije jen v paměti procesu.
- Odesílá se při úspěšném zápisu příchodu (pokud je vyplněný telefon) a
  při změně telefonu na existujícím záznamu.

## E-mail hostiteli (`email_notifier.py`)
- Jen z **iPad kiosku** — tam se jako jediném vybírá `navstiva_koho`
  (krok „za kým jdete"). Recepce/sken tohle pole neposílají, takže tam
  se e-mail nikdy neodešle.
- Po úspěšném zápisu příchodu (ne při `409 jiz_prihlasen`) se `navstiva_koho`
  dohledá v `kontakty.json` podle přesné shody `jmeno` (`najdi_kontakt_podle_jmena`
  v `backend_v2.py`) a pokud má kontakt vyplněný `email`, pošle se mu
  zpráva, že mu dorazila návštěva. Bez shody nebo bez emailu se nic
  neděje — žádná chyba, jen ticho (u fiktivních kontaktů bez emailu je to
  čekaný stav).
- **`email` v `kontakty.json` se NIKDY neposílá do frontendu** —
  `GET /api/kontakty` (veřejný, nepřihlášený endpoint pro kiosek) vrací jen
  `id`/`jmeno`/`oddeleni`. Email čte jen server, pro odeslání notifikace.
- Bez `EMAIL_ENABLED=true` se e-mail jen vypíše do konzole/logu (mock, bez
  nutnosti Resend účtu) — bezpečný výchozí stav pro vývoj.
- Ostrá integrace: **Gmail SMTP** (`smtplib` + `email.message` ze
  standardní knihovny, žádná závislost navíc), ne transakční API služba.
  Důvod přechodu z Resendu: Resend (a podobné služby jako SendGrid) bez
  vlastní ověřené domény pustí e-mail JEN na adresu vlastníka účtu — reálně
  ověřeno, viz commit historie. Gmail SMTP po přihlášení (`GMAIL_ADDRESS` +
  `GMAIL_APP_PASSWORD` z myaccount.google.com/apppasswords) žádné takové
  omezení nemá, jde poslat komukoliv.

## TLS / HTTPS (`tls_proxy.py`, `nastav_https.sh`)
Prohlížeče pustí kameru (`getUserMedia`) jen na zabezpečeném původu.
Flaskův vývojový server se v roli TLS serveru ukázal nespolehlivý (po
restartu přestal reagovat na handshake), proto:
- Flask aplikace běží čistě na **plain HTTP** na `127.0.0.1` (port
  z `PORT`, výchozí 5051 pod `start_demo.sh`).
- `tls_proxy.py` je samostatný proces ze standardní knihovny, který
  na veřejném portu (`EPT_PUBLIC_PORT`, výchozí 5050) dělá TLS
  handshake a bajty jen přelévá dál do Flasku. Čtecí timeout je
  vypnutý pro samotné přelévání (OCR sken na CPU může trvat 15–40 s).
- Certifikát (`nastav_https.sh`) je self-signed, vázaný na aktuální
  LAN IP (`subjectAltName` je povinné, jinak ho moderní prohlížeče
  odmítnou úplně) — po změně sítě je nutné vygenerovat znovu
  (`start_demo.sh` to detekuje a udělá automaticky).
- V produkci za nginx/Caddy TLS řeší reverzní proxy — pak se používá
  `run_produkcne.py` (waitress) bez `tls_proxy.py`.

## GDPR
- Fotografie dokladu se **nikdy neukládá** — zpracuje se jen v paměti
  při volání `/api/ocr` a zahodí.
- Ukládá se pouze: jméno, příjmení, (nepovinně) organizace, SPZ,
  telefon, čas příchodu/odchodu.
- Doporučená informační cedule u vstupu.

## Známá omezení prototypu (testovací provoz)
- OCR rozpoznává spolehlivě jen uzavřený seznam osob (`ZNAMI_LIDE`) —
  u ostatních vyžaduje ruční doplnění jména.
- SQLite bez šifrování.
- Sdílené PINy (admin/správce) místo osobních účtů; role nemají
  odstupňovaná oprávnění.
- Přihlášení nepřežije restart serveru (tokeny jen v paměti).
- Vlastní (self-signed) TLS certifikát — vyžaduje ruční potvrzení v
  prohlížeči.

## QA / testování (`qa/`)
- `qa/demo_data.py` — vyčistí a naplní databázi čistými demo daty
  (mj. osoby pro scénář „Vítejte zpět“).
- `qa/seed.py`, `qa/seed-manifest.json` — obecné naplnění dat pro testy.
- `qa/shots.mjs`, `qa/measure.mjs` — vizuální/automatizované kontroly
  stránek (screenshoty, měření).
- `qa/findings-round*.json` — zaznamenaná zjištění z předchozích kol
  kontrol.

## Poznámky pro úpravy frontendu
- API je vždy volané **relativní cestou** `/api/...` — nikdy nezadávej
  absolutní `http://localhost:...`, rozbilo by to sken přes LAN IP i
  HTTPS (mixed content) a na telefonu by `localhost` mířilo na telefon
  samotný.
- Autentizace admin dashboardu je přes `X-Auth-Token` hlavičku a token
  v `sessionStorage` (klíče `ept_token`, `ept_role`) — `/sken` žádnou
  autentizaci nepoužívá a nesmí ji vyžadovat (jede jako kiosek bez
  účtu).
- Odpověď `/api/navstevnici` (POST) může vrátit `409` se stavem
  `jiz_prihlasen` — frontend to musí umět zobrazit jako informační
  hlášku, ne jako chybu zápisu.
- Odpověď s `vitejte_zpet: true` obsahuje `zprava` k zobrazení —
  frontend ji rovnou vypisuje uživateli.
- CSS proměnné a světlý/tmavý režim jsou sdílené přes `static/ept-theme.css`
  a atribut `data-theme` na `<html>`, ukládaný do `localStorage`
  (`ept_theme`) — nový frontendový kód by měl tento mechanismus
  respektovat, ne zavádět vlastní.

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
- `tls_proxy.py` — jednoduché TLS zakončení ze standardní knihovny
  (přelévá bajty do Flasku na localhostu), protože Flaskův dev server
  se s `ssl_context` ukázal nespolehlivý.
- `run_produkcne.py` — produkční start pod WSGI serverem `waitress`
  (místo Flaskova dev serveru).
- `recepce.html` — hlavní frontend: dashboard recepce (desktop/tablet).
- `sken.html` — mobilní frontend: krokový self-service sken dokladu.
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
| `/api/login` | POST | — | `{role: "admin"\|"spravce", pin}` → `{token, role}` nebo `401` |
| `/api/logout` | POST | token | zruší token |
| `/api/ocr` | POST | — (bez přihlášení, používá i sken-kiosek) | `{image: "<base64>"}` → `{text, jmeno, prijmeni, engine}` |
| `/api/navstevnici` | POST | — (otevřené, zapisuje i recepce i sken-kiosek) | `{jmeno, prijmeni, organizace?, spz?, phone_number?}` → zápis příchodu; `409` při duplicitě aktivní návštěvy |
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
  nainstalované nebo nic nevrátí.
- **Oříznutí karty** (`_orizni_kartu`, přes OpenCV): najde v širší fotce
  obdélník s poměrem stran občanky (~1.585), narovná perspektivu a
  zvětší — zásadně zlepšuje čitelnost fotek z telefonu z dálky.
- **Cílená extrakce** (`_jmeno_prijmeni_z_boxu`): hledá pole
  PŘÍJMENÍ/SURNAME a JMÉNO/GIVEN NAMES fuzzy porovnáním (kvůli OCR
  překlepům v popiscích), **jen v okně** mezi koncem hlavičky dokladu a
  začátkem dalších údajů (datum narození, pohlaví...). Mimo toto okno
  se jméno nikdy nehledá. Bez jistého popisku v okně vrátí **prázdno**
  — záměrně nehádá, aby se nezapsalo špatné jméno.
- **Whitelist známých osob** (`ZNAMI_LIDE`, `uroci_znamou_osobu`):
  testovací provoz je omezen jen na vybrané lidi (aktuálně Simon
  Pistora, William Varga) — stačí čitelné jméno NEBO příjmení kdekoli v
  textu (fuzzy) a zapíše se kanonická hodnota ze seznamu. Přidání
  člověka = přidání řádku do `ZNAMI_LIDE`. Vypnutelné přes
  `OCR_STRICT_WHITELIST=0`, pak se použije obecná extrakce nad
  libovolným dokladem (nedoporučeno na produkčním demu).
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

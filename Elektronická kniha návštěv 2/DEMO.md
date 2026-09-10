# Demo na prezentaci — co udělat a v jakém pořadí

## Před prezentací (v místnosti, kde se bude prezentovat)

```bash
cd "Elektronická kniha návštěv 2"
./nastav_https.sh          # POVINNĚ znovu, když jsi v jiné síti
python3 qa/demo_data.py    # čistá demo data
./start_demo.sh            # spustí aplikaci + TLS proxy
```

`start_demo.sh` si sám všimne, že se změnila IP, a certifikát vygeneruje znovu.
Na konci vypíše obě adresy.

**Telefon si připrav dopředu:** otevři na něm adresu skenu a **odklikni varování
o certifikátu** (Pokročilé → Pokračovat). Bez toho kamera nepojede a nechceš to
řešit před publikem. Ověř, že se kamera spustí.

PINy jsou v `.env` (do gitu se necommitují).

## Průběh dema

| # | Krok | Co se má stát |
|---|---|---|
| 1 | Otevři v telefonu adresu skenu (vypíše ji `start_demo.sh`) | Otevře se stránka skenu |
| 2 | Vyfoť doklad | Formulář se vyplní jménem, fotka se zahodí |
| 3 | Potvrď příchod | Do 20 s se objeví nový řádek na recepci |
| 4 | Zkus zapsat stejnou osobu znovu | „je již přítomen/a od …", žádná duplicita |
| 5 | Klikni na jméno někoho z vracejících se v tabulce | Modal s historií: kolikrát tu byl/a a jak dlouho se pokaždé zdržel/a |
| 6 | Stiskni **Tisk** | Tiskový seznam osob v budově, se sloupcem na podpis |
| 7 | Stiskni **Audit** | Historie akcí včetně pokusů o duplicitní zápis |
| 8 | Stiskni **Export** | CSV pro Excel, s diakritikou |

Pro krok 5 jsou připravení **Alois Zeman**, **Blanka Šťastná**
a **Cyril Havlíček** — každý má dřívější dokončenou návštěvu, takže klik
na jméno ukáže víc než jeden řádek historie.

## Rozpoznávání dokladu

Funguje jen pro **Simona Pistoru** a **Williama Vargu** (`ZNAMI_LIDE`
v `ocr_processor.py`). U jakéhokoli jiného dokladu se vrátí **prázdno** a vyzve
k ručnímu doplnění — radši nic než špatné jméno. Chování se dá přepnout
`OCR_STRICT_WHITELIST=0` v `.env`, ale na demo to nedělej: obecná extrakce může
vyplnit cizí jméno.

První sken po startu trvá ~4 s (načtení modelu), další ~1 s.

## Když něco selže

**Kamera na telefonu se nespustí.** Nepotvrzený certifikát. Otevři adresu
v prohlížeči, potvrď varování, pak zkus sken znovu. Zkontroluj, že adresa
začíná `https://`.

**Telefon stránku vůbec nenajde.** Není ve stejné síti, nebo se změnila IP.
Pusť `./nastav_https.sh` a `./start_demo.sh` znovu.

**Záložní plán bez telefonu:** sken funguje i na notebooku na
`https://localhost:5050/sken` — localhost je zabezpečený původ, takže kamera
jde i bez certifikátu. Použij webkameru.

**Úplný záložní plán:** návštěvníka zapiš ručně ve formuláři vlevo. Všechno
ostatní (duplicity, evakuace, audit, export) funguje bez OCR i bez telefonu.

## Co nezmiňovat jako hotové

Prototyp v testovacím provozu: OCR jen dva lidé, SQLite bez šifrování, společné
PINy místo osobních účtů, přihlášení nepřežije restart serveru, vlastní
certifikát. Všechno je popsané na straně 14 prezentace — je lepší to říct sám
než to nechat objevit.

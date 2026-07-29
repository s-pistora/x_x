# Návštěvní kniha v2 — Instalace a spuštění

## Soubory
- `recepce.html` — Hlavní stránka recepce (přehled, statistiky, ruční zadání)
- `sken.html`    — Mobilní stránka pro sken dokladu
- `backend_v2.py`— Python server (Flask + SQLite + AI OCR)
- `requirements_v2.txt` — Python závislosti

---

## 1. Nastavení

### Získej Anthropic API klíč (pro OCR)
1. Jdi na https://console.anthropic.com/
2. Vytvoř API klíč (Settings → API Keys)
3. Nastav proměnnou prostředí:

```bash
# Linux / macOS
export ANTHROPIC_API_KEY="sk-ant-..."

# Windows (CMD)
set ANTHROPIC_API_KEY=sk-ant-...

# Windows (PowerShell)
$env:ANTHROPIC_API_KEY="sk-ant-..."
```

### Instalace závislostí
```bash
pip install flask flask-cors
```

---

## 2. Spuštění

```bash
python backend_v2.py
```

Server poběží na: **http://localhost:5000**

---

## 3. Otevření aplikace

### Recepce (desktop/tablet):
Otevři `recepce.html` v prohlížeči — nebo spusť:
```bash
python -m http.server 8080
```
→ http://localhost:8080/recepce.html

### Mobilní sken:
1. Na recepci se zobrazí **QR kód**
2. Návštěvník ho naskenuje telefonem
3. Otevře se `sken.html` na jeho telefonu
4. Vyfotí doklad → AI rozpozná jméno → zapíše příchod

> Pro mobilní přístup musí být telefon ve stejné Wi-Fi síti.
> Případně použij ngrok: `ngrok http 8080`

---

## Jak to funguje (tok)

```
[Recepce zobrazí QR]
       ↓
[Návštěvník naskenuje QR telefonem]
       ↓
[Otevře se sken.html → vyfotí doklad]
       ↓
[Foto → backend → Claude Vision OCR → jméno]
       ↓
[Foto se zahodí, uloží se POUZE jméno + příjmení]
       ↓
[Zobrazí se potvrzovací obrazovka → Zapsat příchod]
       ↓
[Záznam v databázi: jméno, org, SPZ, čas příchodu]
       ↓
[Při odchodu recepce klikne Upravit → Zapsat odchod]
```

---

## Databáze
Soubor: `navstevni_kniha.db` (SQLite)

Sloupce: `id, jmeno, prijmeni, organizace, spz, prichod_dt, odchod_dt`

---

## GDPR
- Fotografie průkazu se **nikdy neukládá**
- Ukládá se pouze: jméno, příjmení, čas příchodu/odchodu
- Organizace a SPZ jsou nepovinné
- Doporučujeme informační ceduli u vstupu

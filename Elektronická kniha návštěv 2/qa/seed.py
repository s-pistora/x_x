#!/usr/bin/env python3
"""Naplní návštěvní knihu realistickými daty pro vizuální QA i demo před vedením.

Časy jsou ukotvené k dnešnímu dni v 14:30 (běžná provozní hodina), ne k okamžiku
spuštění — screenshoty pak vypadají stejně bez ohledu na to, kdy se harness pustí.
Referenční čas se zapíše do seed-manifest.json; shots.mjs na něj zmrazí hodiny
prohlížeče, aby sloupec "Doba" a panel "poslední hodina" seděly.
"""
import json, shutil, sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# Odvozeno od umístění skriptu: qa/ leží uvnitř projektu, takže APP je o úroveň výš.
APP = Path(__file__).resolve().parent.parent
DB = APP / "navstevni_kniha.db"
MANIFEST = Path(__file__).resolve().parent / "seed-manifest.json"

# Kotva: dnes 14:30:00
T = datetime.now().replace(hour=14, minute=30, second=0, microsecond=0)

def dt(delta_min):
    return (T - timedelta(minutes=delta_min)).strftime("%Y-%m-%d %H:%M:%S")

# (jméno, příjmení, organizace, spz, příchod před X min, odchod před X min|None)
ZAZNAMY = [
    # ── Aktuálně přítomní, v poslední hodině (levý panel je musí ukázat) ──
    ("Petr",     "Novák",      "Siemens s.r.o.",        "3AB 1122",  8,    None),
    ("Jana",     "Svobodová",  "TÜV SÜD Czech",         "",          25,   None),
    ("Martin",   "Dvořák",     "DHL Express",           "5C7 8890",  47,   None),
    # ── Přítomný, ale déle než hodinu (ověří, že panel filtruje správně) ──
    ("Lukáš",    "Procházka",  "Bosch Rexroth",         "2AE 4471",  130,  None),

    # ── Dnes už odešli (tab Historie, pevná Doba) ──
    ("Eva",      "Horáková",   "KUKA Roboter",          "",          300,  200),
    ("Tomáš",    "Beneš",      "Festo s.r.o.",          "1BC 3344",  375,  285),
    ("Kateřina", "Marková",    "Kärcher",               "8E2 1907",  400,  370),

    # ── Starší dny (tab Vše, hledání podle data) ──
    ("Jiří",     "Kučera",     "ABB s.r.o.",            "4KL 5566",  1590, 1470),
    ("Marie",    "Veselá",     "Schneider Electric",    "",          1710, 1650),
    ("Pavel",    "Černý",      "Murrelektronik",        "7ZZ 2210",  4350, 4230),
    ("Hana",     "Pokorná",    "Phoenix Contact",       "",          7230, 7150),
    ("Ondřej",   "Krejčí",     "SKF Ložiska",           "9AB 8877",  10110, 10020),
]

def main():
    if DB.exists() and not DB.with_suffix(".db.bak").exists():
        shutil.copy2(DB, DB.with_suffix(".db.bak"))
        print(f"záloha → {DB.with_suffix('.db.bak').name}")

    conn = sqlite3.connect(DB)
    conn.execute("DELETE FROM navstevnici")
    conn.execute("DELETE FROM sqlite_sequence WHERE name='navstevnici'")
    for jm, pr, org, spz, prich, odch in ZAZNAMY:
        conn.execute(
            "INSERT INTO navstevnici (jmeno, prijmeni, organizace, spz, prichod_dt, odchod_dt)"
            " VALUES (?,?,?,?,?,?)",
            (jm, pr, org, spz, dt(prich), dt(odch) if odch is not None else None),
        )
    conn.commit()

    pritomni = conn.execute("SELECT COUNT(*) FROM navstevnici WHERE odchod_dt IS NULL").fetchone()[0]
    celkem = conn.execute("SELECT COUNT(*) FROM navstevnici").fetchone()[0]
    conn.close()

    MANIFEST.write_text(json.dumps({
        "reference_time": T.isoformat(),
        "reference_epoch_ms": int(T.timestamp() * 1000),
        "pritomni": pritomni,
        "celkem": celkem,
    }, indent=2), encoding="utf-8")

    print(f"vloženo {celkem} záznamů ({pritomni} přítomných), kotva {T:%Y-%m-%d %H:%M}")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Bohatá demo data pro ruční proklikání všech funkcí.

Rozdíl proti seed.py: `seed.py` je ZÁMĚRNĚ deterministický a kotví čas na 14:30,
protože na něm stojí screenshotový harness (shots.mjs zmrazuje hodiny prohlížeče
na stejnou hodnotu). Tenhle skript naopak staví data relativně ke skutečnému
"teď", aby v prohlížeči tikal živý čítač doby, a míchá je náhodně — je na ruční
zkoušení, ne na regresní snímky.

POZOR: spuštěním seed.py se tahle data přepíšou zpátky na deterministickou
dvanáctku. Pro demo před vedením pouštěj tenhle skript, ne seed.py.

Data jsou postavená tak, aby šla vyzkoušet každá funkce:
  • přítomní s dobou od minut po hodiny  → tab Přítomní, živý čítač Doba
  • dnes odešlí                          → tab Dnes, pevná Doba, skryté tlačítko odchodu
  • starší návštěvy                      → tab Historie, tab Vše, hledání podle data
  • lidé s telefonem i bez               → pole Telefon v modalu, SMS notifikace
  • VRACEJÍCÍ SE lidé (dřív byli, teď ne) → klik na jméno v tabulce ukáže víc než 1 návštěvu v historii
  • právě přítomní                       → detekce duplicity (409) při opakovaném zápisu
  • audit_log                            → historie akcí
"""
import os
import random
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
DB = APP / "navstevni_kniha.db"

# Schéma si vytvoříme sami, ať skript nezávisí na tom, že backend někdy nastartoval
# (a hlavně: sqlite3.connect() na neexistující cestě vyrobí prázdný soubor BEZ
# tabulek, takže „soubor existuje" nic nezaručuje). Použijeme init_db z db_manager,
# aby schéma bylo z jednoho místa — včetně audit_log a migrace phone_number.
# db_manager má DB_PATH relativní, proto se přepneme do složky projektu.
os.chdir(APP)
sys.path.insert(0, str(APP))
import db_manager  # noqa: E402 — až po chdir/sys.path

# Fixní seed → stejný výsledek při každém spuštění, ale rozložení působí náhodně.
random.seed(20260730)

NOW = db_manager.ted()  # místní čas recepce (Europe/Prague), ne čas serveru
F = "%Y-%m-%d %H:%M:%S"

# Reálné dodavatelské a auditorské firmy odpovídající provozu závodu v Habartově.
FIRMY = [
    "Siemens s.r.o.", "Bosch Rexroth", "DHL Express", "TÜV SÜD Czech", "KUKA Roboter",
    "Festo s.r.o.", "Kärcher", "ABB s.r.o.", "Schneider Electric", "Murrelektronik",
    "Phoenix Contact", "SKF Ložiska", "Hennlich", "Zebra Technologies", "Rittal",
    "PPL CZ", "Toyota Material Handling", "Linde Gas", "SICK Sensors", "ČEZ Distribuce",
]
JMENA_M = ["Petr", "Martin", "Lukáš", "Tomáš", "Jiří", "Pavel", "Ondřej", "Jakub",
           "David", "Michal", "Filip", "Radek", "Zdeněk", "Vojtěch", "Marek"]
JMENA_Z = ["Jana", "Eva", "Kateřina", "Marie", "Hana", "Lucie", "Tereza", "Petra",
           "Veronika", "Alena", "Barbora", "Kristýna", "Michaela"]
PRIJMENI_M = ["Novák", "Dvořák", "Procházka", "Beneš", "Kučera", "Černý", "Krejčí",
              "Horák", "Marek", "Pospíšil", "Šimek", "Král", "Fiala", "Sedláček"]
PRIJMENI_Z = ["Svobodová", "Horáková", "Marková", "Veselá", "Pokorná", "Nováková",
              "Dvořáková", "Kučerová", "Krátká", "Bláhová", "Růžičková"]


def spz():
    """Formát reálné české SPZ: číslice, dvě písmena, čtyři číslice."""
    return (f"{random.randint(1, 9)}{random.choice('ABCEHJKLMPSTVZ')}"
            f"{random.choice('ABCEHJKLMPSTVZ')} {random.randint(1000, 9999)}")


def telefon():
    return f"+420{random.randint(601, 799)}{random.randint(100000, 999999)}"


def osoba():
    if random.random() < 0.45:
        return random.choice(JMENA_Z), random.choice(PRIJMENI_Z)
    return random.choice(JMENA_M), random.choice(PRIJMENI_M)


def main():
    # Zálohu děláme jen když je co zachraňovat — prázdný soubor bez tabulek by
    # jinak přepsal případnou starší použitelnou zálohu.
    if DB.exists() and DB.stat().st_size > 0:
        shutil.copy(DB, DB.with_suffix(".db.bak"))
        print(f"záloha → {DB.name}.bak")

    db_manager.init_db()
    print("schéma ověřeno (navstevnici + audit_log)")

    conn = sqlite3.connect(DB)
    conn.execute("DELETE FROM navstevnici")
    conn.execute("DELETE FROM audit_log")
    conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('navstevnici','audit_log')")

    # Řádky se nejdřív posbírají a teprve pak vloží v chronologickém pořadí, aby id
    # rostlo s časem stejně jako za provozu. Není to kosmetika: kód, který se ptá
    # „kdy tu byl naposledy“, se o tenhle vztah opíral (viz oprava řazení
    # v db_manager.najdi_posledni_navstevu).
    pending = []   # (prichod, odchod, jmeno, prijmeni, firma, spz, tel, [(action, kdy, details)])

    def vloz(jmeno, prijmeni, firma, znacka, tel, prichod, odchod, akce=()):
        pending.append([prichod, odchod, jmeno, prijmeni, firma, znacka, tel, list(akce)])
        return len(pending) - 1        # index do pending, ne id — to vznikne až při vkládání

    def audit(idx, action, kdy, details=""):
        pending[idx][7].append((action, kdy, details))

    # ── 1) PRÁVĚ PŘÍTOMNÍ — doba od pár minut po půl dne ────────────────────────
    # Škála je schválně široká, ať sloupec Doba ukáže minuty, desítky minut
    # i hodiny a bylo vidět, že se opravdu počítá.
    pritomni_min = [4, 11, 23, 38, 52, 77, 132, 194, 271, 355]
    print("\npřítomní (odchod_dt IS NULL):")
    for m in pritomni_min:
        j, p = osoba()
        tel = telefon() if random.random() < 0.5 else ""
        zn = spz() if random.random() < 0.7 else ""
        prichod = NOW - timedelta(minutes=m)
        nid = vloz(j, p, random.choice(FIRMY), zn, tel, prichod, None)
        audit(nid, "novy_navstevnik", prichod)
        h, mm = divmod(m, 60)
        print(f"  {j} {p:<12} doba {f'{h} h {mm} min' if h else f'{mm} min'}"
              f"{'  tel ' + tel if tel else ''}")

    # ── 2) DNES UŽ ODEŠLÍ — pro tab Dnes a pevnou hodnotu ve sloupci Doba ──────
    print("\ndnes odešlí:")
    for _ in range(12):
        j, p = osoba()
        delka = random.randint(15, 320)
        prichod = NOW - timedelta(minutes=random.randint(delka + 20, 700))
        if prichod.date() != NOW.date():                 # ať zůstane v dnešním dni
            prichod = NOW.replace(hour=6, minute=random.randint(0, 59), second=0)
        odchod = prichod + timedelta(minutes=delka)
        if odchod > NOW:
            odchod = NOW - timedelta(minutes=5)
        tel = telefon() if random.random() < 0.4 else ""
        nid = vloz(j, p, random.choice(FIRMY), spz() if random.random() < 0.6 else "",
                   tel, prichod, odchod)
        audit(nid, "novy_navstevnik", prichod)
        audit(nid, "odchod_zapsan", odchod)
    print(f"  12 záznamů s vyplněným odchodem")

    # ── 3) STARŠÍ NÁVŠTĚVY — tab Historie, tab Vše, hledání podle data ─────────
    print("\nstarší návštěvy:")
    for _ in range(26):
        j, p = osoba()
        dnu = random.randint(1, 60)
        prichod = (NOW - timedelta(days=dnu)).replace(
            hour=random.randint(6, 16), minute=random.choice([0, 10, 15, 20, 30, 40, 45, 50]),
            second=0, microsecond=0)
        odchod = prichod + timedelta(minutes=random.randint(20, 300))
        nid = vloz(j, p, random.choice(FIRMY), spz() if random.random() < 0.6 else "",
                   telefon() if random.random() < 0.3 else "", prichod, odchod)
        audit(nid, "novy_navstevnik", prichod)
        audit(nid, "odchod_zapsan", odchod)
    print(f"  26 záznamů za posledních 60 dnů")

    # ── 4) VRACEJÍCÍ SE LIDÉ ───────────────────────────────────────────────────
    # Klíčové pro test historie návštěv (klik na jméno v tabulce): osoba MUSÍ
    # mít dřívější DOKONČENOU návštěvu a NESMÍ být právě přítomná. Tyhle tři
    # jsou na to připravené a jejich jména vypíšu, aby se to dalo hned vyzkoušet.
    vracejici = [
        ("Alois", "Zeman", "ČEZ Distribuce", 3),
        ("Blanka", "Šťastná", "TÜV SÜD Czech", 9),
        ("Cyril", "Havlíček", "Linde Gas", 21),
    ]
    print("\nvracející se (dřív byli, teď NEjsou přítomní) — na test historie návštěv:")
    for j, p, firma, dnu in vracejici:
        # Dvě dokončené návštěvy v minulosti, ať je vidět i opakovaná historie.
        # Od nejstarší k nejnovější, aby první byla „novy_navstevnik“ a druhá
        # „opakovana_navsteva“ — v obráceném pořadí by audit tvrdil nesmysl.
        for k, d in enumerate(sorted((dnu, dnu + random.randint(20, 40)), reverse=True)):
            prichod = (NOW - timedelta(days=d)).replace(
                hour=random.randint(7, 15), minute=random.choice([0, 15, 30, 45]),
                second=0, microsecond=0)
            odchod = prichod + timedelta(minutes=random.randint(45, 240))
            idx = vloz(j, p, firma, spz(), telefon(), prichod, odchod)
            audit(idx, "opakovana_navsteva" if k else "novy_navstevnik", prichod)
            audit(idx, "odchod_zapsan", odchod)
        print(f"  {j} {p:<12} poslední návštěva před {dnu} dny ({firma})")

    # ── 5) Audit: pár pokusů o opakovaný zápis už přítomné osoby ──────────────
    aktivni_idx = [i for i, r in enumerate(pending) if r[1] is None]
    for idx in random.sample(aktivni_idx, 3):
        audit(idx, "jiz_prihlasen", NOW - timedelta(minutes=random.randint(1, 30)),
              f"Pokus o opakovaný zápis, osoba je stále přítomna od "
              f"{pending[idx][0].strftime(F)}")

    # ── Vlastní zápis: chronologicky, ať id roste s časem ──────────────────────
    for prichod, odchod, j, p, firma, znacka, tel, akce in sorted(pending, key=lambda r: r[0]):
        cur = conn.execute(
            "INSERT INTO navstevnici (jmeno, prijmeni, organizace, spz, phone_number, "
            "prichod_dt, odchod_dt) VALUES (?,?,?,?,?,?,?)",
            (j, p, firma, znacka, tel,
             prichod.strftime(F), odchod.strftime(F) if odchod else None))
        for action, kdy, details in akce:
            conn.execute(
                "INSERT INTO audit_log (navstevnik_id, action, timestamp, details) "
                "VALUES (?,?,?,?)",
                (cur.lastrowid, action, kdy.strftime(F), details))

    conn.commit()

    celkem = conn.execute("SELECT COUNT(*) FROM navstevnici").fetchone()[0]
    akt    = conn.execute("SELECT COUNT(*) FROM navstevnici WHERE odchod_dt IS NULL").fetchone()[0]
    dnes   = conn.execute("SELECT COUNT(*) FROM navstevnici WHERE prichod_dt LIKE ?",
                          (NOW.strftime("%Y-%m-%d") + "%",)).fetchone()[0]
    stel   = conn.execute("SELECT COUNT(*) FROM navstevnici WHERE phone_number != ''").fetchone()[0]
    audits = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    conn.close()

    print(f"\nhotovo: {celkem} záznamů, {akt} přítomných, {dnes} dnešních, "
          f"{stel} s telefonem, {audits} položek v audit_log")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Databázová vrstva – návštěvníci a audit log."""
import sqlite3
import unicodedata
from datetime import datetime

DB_PATH = "navstevni_kniha.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ma_sloupec(conn, tabulka, sloupec):
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({tabulka})")]
    return sloupec in cols


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS navstevnici (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                jmeno        TEXT NOT NULL,
                prijmeni     TEXT NOT NULL,
                organizace   TEXT DEFAULT '',
                spz          TEXT DEFAULT '',
                phone_number TEXT DEFAULT '',
                navstiva_koho TEXT DEFAULT '',
                prichod_dt   TEXT NOT NULL,
                odchod_dt    TEXT
            )
        """)
        # Migrace pro DB založené před přidáním telefonu
        if not _ma_sloupec(conn, "navstevnici", "phone_number"):
            conn.execute("ALTER TABLE navstevnici ADD COLUMN phone_number TEXT DEFAULT ''")
        # Migrace pro DB založené před přidáním iPad kiosku (koho návštěvník navštěvuje)
        if not _ma_sloupec(conn, "navstevnici", "navstiva_koho"):
            conn.execute("ALTER TABLE navstevnici ADD COLUMN navstiva_koho TEXT DEFAULT ''")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                navstevnik_id INTEGER,
                action        TEXT NOT NULL,
                timestamp     TEXT NOT NULL,
                details       TEXT DEFAULT ''
            )
        """)
        conn.commit()


def strip_diakritiku(s):
    """Odstraní diakritiku – používá se jen pro porovnávání jmen, ne pro zápis."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", s or "")
        if not unicodedata.combining(c)
    )


def _normalizuj(jmeno, prijmeni):
    return strip_diakritiku(jmeno).strip().lower(), strip_diakritiku(prijmeni).strip().lower()


def zapis_audit(conn, navstevnik_id, action, details=""):
    conn.execute(
        "INSERT INTO audit_log (navstevnik_id, action, timestamp, details) VALUES (?,?,?,?)",
        (navstevnik_id, action, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), details)
    )


def najdi_aktivni_navstevu(conn, jmeno, prijmeni):
    """Vrátí řádek, pokud je tato osoba aktuálně v budově (odchod_dt IS NULL)."""
    nj, npr = _normalizuj(jmeno, prijmeni)
    for row in conn.execute("SELECT * FROM navstevnici WHERE odchod_dt IS NULL"):
        if _normalizuj(row["jmeno"], row["prijmeni"]) == (nj, npr):
            return row
    return None


def najdi_posledni_navstevu(conn, jmeno, prijmeni):
    """Vrátí poslední (uzavřenou) návštěvu té samé osoby, pokud existuje – pro 'vítejte zpět'.

    Řadí se podle prichod_dt, ne podle id: „poslední“ je otázka na čas, a pořadí
    vkládání se s časem krylo jen dokud data vznikala výhradně za provozu. Při
    importu nebo naplnění demo daty mimo chronologické pořadí vracelo id DESC
    nejstarší návštěvu, takže hláška ukazovala špatné datum. Formát
    "YYYY-MM-DD HH:MM:SS" se řadí lexikograficky = chronologicky.
    """
    nj, npr = _normalizuj(jmeno, prijmeni)
    for row in conn.execute("SELECT * FROM navstevnici WHERE odchod_dt IS NOT NULL "
                            "ORDER BY prichod_dt DESC"):
        if _normalizuj(row["jmeno"], row["prijmeni"]) == (nj, npr):
            return row
    return None


def zapis_prichod(jmeno, prijmeni, organizace, spz, phone_number, navstiva_koho=""):
    """
    Zapíše příchod návštěvníka. Kniha návštěv záměrně loguje KAŽDOU návštěvu jako
    samostatný řádek (historie), proto se duplicitě předchází jen v jednom případě:
    pokud je osoba PRÁVĚ TEĎ aktivní (ještě neodešla) – tehdy se druhý aktivní
    záznam nezakládá. Pokud osoba už dříve byla a odešla, jde o novou návštěvu a
    založí se nový řádek, jen s hláškou "vítejte zpět" odkazující na tu předchozí.
    """
    with get_db() as conn:
        aktivni = najdi_aktivni_navstevu(conn, jmeno, prijmeni)
        if aktivni:
            if phone_number:
                conn.execute(
                    "UPDATE navstevnici SET phone_number=? WHERE id=?",
                    (phone_number, aktivni["id"])
                )
            zapis_audit(conn, aktivni["id"], "jiz_prihlasen",
                        f"Pokus o opakovaný zápis, osoba je stále přítomna od {aktivni['prichod_dt']}")
            conn.commit()
            return {
                "status":       "jiz_prihlasen",
                "id":           aktivni["id"],
                "prichod_dt":   aktivni["prichod_dt"],
                "vitejte_zpet": False,
            }

        posledni = najdi_posledni_navstevu(conn, jmeno, prijmeni)
        prichod = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cur = conn.execute(
            "INSERT INTO navstevnici (jmeno, prijmeni, organizace, spz, phone_number, navstiva_koho, prichod_dt) "
            "VALUES (?,?,?,?,?,?,?)",
            (jmeno, prijmeni, organizace, spz, phone_number, navstiva_koho, prichod)
        )
        new_id = cur.lastrowid

        if posledni:
            zapis_audit(conn, new_id, "opakovana_navsteva", f"Předchozí návštěva: {posledni['prichod_dt']}")
        else:
            zapis_audit(conn, new_id, "novy_navstevnik", "")

        conn.commit()

        return {
            "status":           "ok",
            "id":               new_id,
            "prichod_dt":       prichod,
            "vitejte_zpet":     posledni is not None,
            "posledni_navsteva": posledni["prichod_dt"] if posledni else None,
        }


def aktualizuj_telefon(nav_id, novy_telefon):
    """Aktualizuje telefon u záznamu a zaloguje změnu, pokud se liší od původního."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM navstevnici WHERE id=?", (nav_id,)).fetchone()
        if not row:
            return False, False
        zmenil_se = (row["phone_number"] or "") != (novy_telefon or "")
        conn.execute("UPDATE navstevnici SET phone_number=? WHERE id=?", (novy_telefon, nav_id))
        if zmenil_se:
            zapis_audit(conn, nav_id, "telefon_zmenen", f"'{row['phone_number']}' -> '{novy_telefon}'")
        conn.commit()
        return True, zmenil_se

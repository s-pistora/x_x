# -*- coding: utf-8 -*-
"""Runner testovací sady OCR.

Zavolá precti_doklad(pil_image) na všechny vygenerované obrázky a vytiskne
Markdown tabulku  doklad × degradace × (jméno | příjmení | engine)  pro
zvolený režim whitelistu. Dá se pouštět opakovaně (baseline i „after").

Použití (z adresáře aplikace):
    PYTHONUTF8=1 venv/Scripts/python.exe ocr_tests/spust_sadu.py --strict 1 --modul ocr_processor
    PYTHONUTF8=1 venv/Scripts/python.exe ocr_tests/spust_sadu.py --strict 0 --modul _baseline_ocr

Parametry:
    --strict {0,1}   nastaví OCR_STRICT_WHITELIST PŘED importem modulu (default 1)
    --modul NAZEV    který modul importovat (default "ocr_processor";
                     baseline = "_baseline_ocr")
"""
import os
import sys
import argparse
import importlib

HERE = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(HERE, "img")
APP_DIR = os.path.dirname(HERE)  # adresář aplikace (kde je ocr_processor.py)

# Pořadí dokladů v tabulce (řádky).
DOKLADY = [
    "obcanka",
    "ridicak_se_slovy",
    "ridicak_jen_cisla",
    "personalausweis",
    "ceske_jmeno_ss",
    "zdravotni_predni_pohromade",
    "zdravotni_predni_oddelene",
    "zdravotni_ehic_zadni",
]

# Degradace: (přípona souboru, přípona názvu, popisek do tabulky).
DEGRADACE = [
    ("", "png", "(čistá)"),
    ("_sum", "png", "šum"),
    ("_rotace", "png", "rotace"),
    ("_rozmazani", "png", "rozmazání"),
    ("_jpeg40", "jpg", "jpeg40"),
]


def _bunka(s):
    """Prázdný řetězec zobraz jako '—', jinak escapuj svislítko pro Markdown."""
    s = (s or "").strip()
    if not s:
        return "—"
    return s.replace("|", "\\|")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", choices=["0", "1"], default="1")
    ap.add_argument("--modul", default="ocr_processor")
    args = ap.parse_args()

    # DŮLEŽITÉ: STRIKTNI_WHITELIST se v modulu čte při importu, proto nastavit TEĎ.
    os.environ["OCR_STRICT_WHITELIST"] = args.strict

    # Aby šel importovat jak ocr_processor (z app dir), tak _baseline_ocr (z ocr_tests).
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    if APP_DIR not in sys.path:
        sys.path.insert(0, APP_DIR)

    from PIL import Image
    ocr = importlib.import_module(args.modul)

    print(f"## Režim: OCR_STRICT_WHITELIST={args.strict}  ·  modul=`{args.modul}`")
    print()
    print("| Doklad | Degradace | jméno | příjmení | engine |")
    print("|---|---|---|---|---|")

    for doklad in DOKLADY:
        for suf, ext, popis in DEGRADACE:
            fname = f"{doklad}{suf}.{ext}"
            path = os.path.join(IMG_DIR, fname)
            if not os.path.exists(path):
                print(f"| {doklad} | {popis} | _chybí soubor_ | {fname} | — |")
                continue
            sys.stderr.write(f"[{args.modul} strict={args.strict}] {fname} ... ")
            sys.stderr.flush()
            try:
                jmeno, prijmeni, _text, engine = ocr.precti_doklad(Image.open(path))
            except Exception as e:  # noqa: BLE001 – chceme to vidět v tabulce, ne spadnout
                print(f"| {doklad} | {popis} | _CHYBA_ | {type(e).__name__}: {e} | — |")
                sys.stderr.write("CHYBA\n")
                continue
            sys.stderr.write(f"jméno={jmeno!r} příjmení={prijmeni!r}\n")
            print(f"| {doklad} | {popis} | {_bunka(jmeno)} | {_bunka(prijmeni)} | {_bunka(engine)} |")

    print()
    print("_Legenda: „—“ = prázdné pole (OCR nic jistého nevrátilo)._")


if __name__ == "__main__":
    main()

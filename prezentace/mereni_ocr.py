#!/usr/bin/env python3
"""Reálná měření OCR pro prezentaci — čísla do decku se nesmí odhadovat.

Vyrobí vzorový doklad (zřetelně označený jako VZOR, ať ho nikdo nepovažuje za
skutečný), pustí přes něj skutečnou OCR pipeline a změří:
  · co OCR doslova přečetlo
  · co se z toho zapíše
  · jak dlouho to trvalo
  · co se stane s rozmazaným snímkem (proč se sbírá série, ne jedno cvaknutí)
  · co se stane s cizím dokladem (striktní whitelist)

Výstup: prezentace/mereni.json + obrázky dokladu do prezentace/snimky/.
"""
import json
import os
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
APP = HERE.parent / "Elektronická kniha návštěv 2"
SNIMKY = HERE / "snimky"
SNIMKY.mkdir(exist_ok=True)

os.chdir(APP)
sys.path.insert(0, str(APP))
import ocr_processor as ocr  # noqa: E402


def font(velikost, tucne=False):
    cesta = "/System/Library/Fonts/Helvetica.ttc"
    try:
        return ImageFont.truetype(cesta, velikost, index=1 if tucne else 0)
    except Exception:
        return ImageFont.load_default()


def doklad(prijmeni, jmeno, sirka=1000):
    """Vzorový občanský průkaz. Rozvržení odpovídá skutečnému dokladu jen natolik,
    aby dávalo smysl demonstrovat čtení podle pozice polí."""
    v = int(sirka * 0.63)
    im = Image.new("RGB", (sirka, v), "#e9e3d6")
    d = ImageDraw.Draw(im)

    # jemný podtisk, ať to nevypadá jako prázdný papír
    for y in range(0, v, 6):
        d.line([(0, y), (sirka, y)], fill="#e4ded1", width=1)

    d.rectangle([0, 0, sirka, int(v * 0.11)], fill="#a70a1b")
    d.text((int(sirka * .03), int(v * .032)), "ČESKÁ REPUBLIKA · OBČANSKÝ PRŮKAZ",
           fill="white", font=font(int(v * .046), True))

    # fotka
    fx, fy = int(sirka * .04), int(v * .18)
    fw, fh = int(sirka * .22), int(v * .58)
    d.rectangle([fx, fy, fx + fw, fy + fh], fill="#cdc6b6", outline="#a49c8b", width=2)
    d.text((fx + fw // 2 - int(sirka * .028), fy + fh // 2), "FOTO",
           fill="#8a8271", font=font(int(v * .04)))

    tx = fx + fw + int(sirka * .05)
    pole = [("PŘÍJMENÍ / SURNAME", prijmeni), ("JMÉNO / GIVEN NAMES", jmeno),
            ("DATUM NAROZENÍ", "14. 03. 1988"), ("ČÍSLO DOKLADU", "123456789")]
    y = int(v * .19)
    for popisek, hodnota in pole:
        d.text((tx, y), popisek, fill="#6b6455", font=font(int(v * .034)))
        d.text((tx, y + int(v * .045)), hodnota, fill="#161616", font=font(int(v * .062), True))
        y += int(v * .155)

    # Zřetelné označení, že jde o vzor — v prezentaci nesmí vzniknout dojem,
    # že ukazujeme cizí skutečný doklad.
    d.text((int(sirka * .62), int(v * .87)), "VZOR / SPECIMEN",
           fill="#b03a45", font=font(int(v * .05), True))
    return im


def zmer(popis, obrazek):
    t = time.time()
    jmeno, prijmeni, text, engine = ocr.precti_doklad(obrazek)
    trvani = time.time() - t
    return {
        "popis": popis,
        "jmeno": jmeno,
        "prijmeni": prijmeni,
        "engine": engine,
        "sekundy": round(trvani, 2),
        "precteny_text": text,
        "radku_textu": len([r for r in text.splitlines() if r.strip()]),
    }


def main():
    ostry = doklad("PISTORA", "SIMON")
    ostry.save(SNIMKY / "doklad-ostry.png")

    # Rozmazání odpovídá běžnému záběru z ruky bez zaostření.
    rozmazany = ostry.filter(ImageFilter.GaussianBlur(radius=4.2))
    rozmazany.save(SNIMKY / "doklad-rozmazany.png")

    cizi = doklad("SVOBODOVÁ", "JANA")
    cizi.save(SNIMKY / "doklad-cizi.png")

    print("zahřívám model…", flush=True)
    ocr.predehrej()

    vysledky = []
    for popis, im in [("ostrý snímek", ostry),
                      ("rozmazaný snímek", rozmazany),
                      ("cizí doklad (mimo seznam)", cizi)]:
        r = zmer(popis, im)
        vysledky.append(r)
        vypis = f"{r['jmeno']} {r['prijmeni']}".strip() or "— prázdno —"
        print(f"  {popis:<28} {r['sekundy']:5.2f}s  →  {vypis}", flush=True)

    # Opakované čtení ostrého snímku — ustálená doba, bez načítání modelu.
    casy = [zmer("opakování", ostry)["sekundy"] for _ in range(4)]
    print(f"  opakovaná čtení: {casy}", flush=True)

    out = {
        "vysledky": vysledky,
        "opakovane_casy": casy,
        "medianovy_cas": sorted(casy)[len(casy) // 2],
        "znami_lide": ocr.ZNAMI_LIDE,
        "striktni_whitelist": ocr.STRIKTNI_WHITELIST,
    }
    (HERE / "mereni.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nuloženo do {HERE / 'mereni.json'}")


if __name__ == "__main__":
    main()

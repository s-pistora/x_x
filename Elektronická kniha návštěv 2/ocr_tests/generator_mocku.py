# -*- coding: utf-8 -*-
"""Generátor syntetických mock dokladů pro testovací sadu OCR.

Vytváří ČISTÉ layouty (ne falzifikáty – žádná pravá loga/hologramy), jen
popisek + hodnota, aby se dalo ověřit chování extrakce jména/příjmení.
Ke každému dokladu navíc uloží 4 degradované varianty blíž fotce z telefonu:
    _sum        – gaussovský šum
    _rotace     – náklon (±3–5°)
    _rozmazani  – zmenšení na ~60 % a zpět (ztráta detailu)
    _jpeg40     – uložení jako JPEG kvalita 40 (blokové artefakty)

Layout je převzatý z fungujících generátorů ve scratchpadu (popisek VLEVO,
hodnota VPRAVO na stejném řádku – tak to má reálná občanka).

Spuštění (z adresáře aplikace):
    PYTHONUTF8=1 venv/Scripts/python.exe ocr_tests/generator_mocku.py
"""
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Determinismus – aby before/after běžely nad identickými obrázky i po regeneraci.
random.seed(42)
np.random.seed(42)

HERE = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(HERE, "img")
os.makedirs(IMG_DIR, exist_ok=True)

F = r"C:\Windows\Fonts\arial.ttf"
FB = r"C:\Windows\Fonts\arialbd.ttf"


def font(sz, bold=False):
    return ImageFont.truetype(FB if bold else F, sz)


def _na_pozadi(card):
    """Vloží kartu na větší šedé pozadí (jako fotka dokladu na stole)."""
    W, H = card.size
    bg = Image.new("RGB", (int(W * 1.3), int(H * 1.3)), (120, 120, 120))
    bg.paste(card, ((bg.width - W) // 2, (bg.height - H) // 2))
    return bg


def make_card(rows, header_lines, bg_color="white", header_color=(30, 60, 120)):
    """rows: (label, value) – popisek vlevo (dělený ' / ' pod sebe), hodnota VPRAVO."""
    W, H = 1000, 630
    card = Image.new("RGB", (W, H), bg_color)
    d = ImageDraw.Draw(card)
    d.rectangle([0, 0, W - 1, 90], fill=header_color)
    y = 18
    for i, hl in enumerate(header_lines):
        d.text((30, y), hl, font=font(26 if i == 0 else 20, bold=(i == 0)), fill="white")
        y += 34
    y = 160
    for label, value in rows:
        for j, lp in enumerate(label.split(" / ")):
            d.text((40, y + j * 30), lp, font=font(22), fill=(90, 90, 90))
        d.text((520, y + 4), value, font=font(44, bold=True), fill=(10, 10, 10))
        y += 110
    return _na_pozadi(card)


# ── Zdravotní průkazy (převzato z gen_zdravotni.py) ──────────────────────────────
def zdrav_predni_pohromade():
    """Český průkaz pojištěnce – přední strana. Jméno POHROMADĚ (NOVÁK JAN)."""
    W, H = 1000, 630
    c = Image.new("RGB", (W, H), (235, 240, 250))
    d = ImageDraw.Draw(c)
    d.rectangle([0, 0, W - 1, 100], fill=(0, 90, 160))
    d.text((30, 20), "Všeobecná zdravotní pojišťovna ČR", font=font(26, True), fill="white")
    d.text((30, 58), "Průkaz pojištěnce", font=font(22), fill="white")
    d.text((40, 200), "NOVÁK JAN", font=font(50, True), fill=(10, 10, 10))
    d.text((40, 320), "Číslo pojištěnce", font=font(22), fill=(90, 90, 90))
    d.text((40, 350), "9001011234", font=font(40, True), fill=(10, 10, 10))
    d.text((40, 440), "Kód pojišťovny  111", font=font(24), fill=(60, 60, 60))
    return _na_pozadi(c)


def zdrav_predni_oddelene():
    """Přední strana s oddělenými popisky Příjmení / Jméno (hodnota vpravo)."""
    W, H = 1000, 630
    c = Image.new("RGB", (W, H), (235, 240, 250))
    d = ImageDraw.Draw(c)
    d.rectangle([0, 0, W - 1, 100], fill=(0, 90, 160))
    d.text((30, 20), "Zdravotní pojišťovna", font=font(26, True), fill="white")
    d.text((30, 58), "Průkaz pojištěnce", font=font(22), fill="white")
    d.text((40, 180), "Příjmení", font=font(24), fill=(90, 90, 90))
    d.text((520, 178), "NOVÁK", font=font(46, True), fill=(10, 10, 10))
    d.text((40, 280), "Jméno", font=font(24), fill=(90, 90, 90))
    d.text((520, 278), "JAN", font=font(46, True), fill=(10, 10, 10))
    d.text((40, 400), "Číslo pojištěnce", font=font(24), fill=(90, 90, 90))
    d.text((520, 400), "9001011234", font=font(36, True), fill=(10, 10, 10))
    return _na_pozadi(c)


def zdrav_ehic_zadni():
    """EHIC – zadní modrá strana s číslovanými poli 3./4."""
    W, H = 1000, 630
    c = Image.new("RGB", (W, H), (150, 180, 220))
    d = ImageDraw.Draw(c)
    d.text((30, 20), "EVROPSKÝ PRŮKAZ ZDRAVOTNÍHO POJIŠTĚNÍ", font=font(24, True), fill=(0, 30, 90))
    rows = [
        ("3. Příjmení", "NOVÁK"),
        ("4. Jméno", "JAN"),
        ("5. Datum narození", "01/01/1990"),
        ("6. Osobní identifikační číslo", "9001011234"),
        ("7. Číslo instituce", "1111"),
        ("8. Číslo karty", "80280000000000001"),
    ]
    y = 90
    for lab, val in rows:
        d.text((40, y), lab, font=font(22), fill=(0, 30, 90))
        d.text((560, y - 4), val, font=font(30, True), fill=(10, 10, 10))
        y += 78
    return _na_pozadi(c)


# ── Definice všech dokladů (základní čisté obrázky) ──────────────────────────────
def postav_zaklady():
    return {
        "obcanka": make_card(
            [("Příjmení / Surname", "NOVÁK"),
             ("Jméno / Given names", "JAN"),
             ("Datum narození / Date of birth", "01.01.1990")],
            ["ČESKÁ REPUBLIKA", "OBČANSKÝ PRŮKAZ / IDENTITY CARD"]),
        "ridicak_se_slovy": make_card(
            [("1. Příjmení / Surname", "NOVÁK"),
             ("2. Jméno / Given names", "JAN"),
             ("3. Datum narození", "01.01.1990")],
            ["ČESKÁ REPUBLIKA", "ŘIDIČSKÝ PRŮKAZ / DRIVING LICENCE"]),
        "ridicak_jen_cisla": make_card(
            [("1.", "NOVÁK"),
             ("2.", "JAN"),
             ("3.", "01.01.1990")],
            ["ČESKÁ REPUBLIKA", "ŘIDIČSKÝ PRŮKAZ / DRIVING LICENCE"]),
        "personalausweis": make_card(
            [("Name", "MÜLLER"),
             ("Vorname", "HANS"),
             ("Geburtsdatum", "01.01.1990")],
            ["BUNDESREPUBLIK DEUTSCHLAND", "PERSONALAUSWEIS"]),
        "ceske_jmeno_ss": make_card(
            [("Příjmení / Surname", "MÜLLER"),
             ("Jméno / Given names", "WEIß"),
             ("Datum narození / Date of birth", "01.01.1990")],
            ["ČESKÁ REPUBLIKA", "OBČANSKÝ PRŮKAZ / IDENTITY CARD"]),
        "zdravotni_predni_pohromade": zdrav_predni_pohromade(),
        "zdravotni_predni_oddelene": zdrav_predni_oddelene(),
        "zdravotni_ehic_zadni": zdrav_ehic_zadni(),
    }


# ── Degradace (blíž fotce z telefonu) ────────────────────────────────────────────
def deg_sum(img):
    """Gaussovský šum."""
    arr = np.array(img.convert("RGB")).astype(np.int16)
    sum_ = np.random.normal(0, 22, arr.shape)
    arr = np.clip(arr + sum_, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def deg_rotace(img):
    """Náklon o pevný úhel v rozsahu ±3–5° (deterministicky přes seedovaný random)."""
    uhel = random.choice([-1, 1]) * random.uniform(3, 5)
    return img.rotate(uhel, resample=Image.BICUBIC, expand=True, fillcolor=(120, 120, 120))


def deg_rozmazani(img):
    """Zmenšit na ~60 % a zpět – simuluje ztrátu ostrosti z dálky."""
    W, H = img.size
    small = img.resize((max(1, int(W * 0.6)), max(1, int(H * 0.6))), Image.LANCZOS)
    return small.resize((W, H), Image.LANCZOS)


def uloz_varianty(zaklad, jmeno):
    """Uloží čistou verzi (.png) + 4 degradované varianty."""
    cesty = []

    def _uloz(img, pripona, fmt="PNG", **kw):
        ext = "jpg" if fmt == "JPEG" else "png"
        p = os.path.join(IMG_DIR, f"{jmeno}{pripona}.{ext}")
        img.convert("RGB").save(p, fmt, **kw)
        cesty.append(os.path.basename(p))

    _uloz(zaklad, "")                       # čistá
    _uloz(deg_sum(zaklad), "_sum")
    _uloz(deg_rotace(zaklad), "_rotace")
    _uloz(deg_rozmazani(zaklad), "_rozmazani")
    _uloz(zaklad, "_jpeg40", "JPEG", quality=40)
    return cesty


def main():
    zaklady = postav_zaklady()
    vse = []
    for jmeno, img in zaklady.items():
        vse.extend(uloz_varianty(img, jmeno))
    print(f"Vygenerováno {len(vse)} obrázků do: {IMG_DIR}")
    for c in vse:
        print("  ", c)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""OCR zpracování dokladu: rozpoznání textu + extrakce jména/příjmení.

Hlavní engine je EasyOCR (lokální neuronová síť, běží offline a zdarma), který
na fotkách dokladů čte výrazně líp než Tesseract. Tesseract zůstává jako záloha
pro případ, že EasyOCR není nainstalované. Extrakce jména umí VELKÁ písmena
z české občanky a filtruje hlavičkové výrazy.
"""
import os
import re
import threading

# Torch (pod EasyOCR) si jinak rozjede vlastní pool vláken, což se s vláknovým
# webserverem tluče — v našem případě to zablokovalo celý server včetně TLS
# handshake. Jedno vlákno navíc dělá dobu rozpoznání předvídatelnou, což je pro
# sken u vrátnice důležitější než špičkový výkon. Nastavit se to musí PŘED
# importem torche, proto tady a ne níž.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np
import pytesseract
from PIL import Image

# Rozpoznávání pouštíme jen jedno v jednom okamžiku. EasyOCR (potažmo torch pod
# ním) není vláknově bezpečný: když se model načítal na pozadí a současně přišel
# první požadavek z jiného vlákna, celý server se zaseknul bez chyby a bez logu.
# Sken navíc posílá až 12 snímků a telefonů může být víc než jeden.
_ocr_lock = threading.Lock()

# Použijeme přesnější český model tessdata_best z projektové složky ./tessdata,
# pokud tam je. Nastavením TESSDATA_PREFIX na tuhle složku ho Tesseract načte
# přednostně před systémovým (starším) modelem – bez sahání do Homebrew.
# Když složka chybí, spadne to zpět na systémový model (nic se nerozbije).
_TESSDATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tessdata")
if os.path.exists(os.path.join(_TESSDATA_DIR, "ces.traineddata")):
    os.environ["TESSDATA_PREFIX"] = _TESSDATA_DIR


# ── EasyOCR (hlavní engine) ─────────────────────────────────────────────────────
# EasyOCR je neuronová síť běžící LOKÁLNĚ a ZDARMA (žádný cloud). Na fotkách
# dokladů z webkamery čte výrazně líp než Tesseract. Model se načítá líně
# (až při prvním použití) a drží se v paměti, takže první sken je pomalejší
# a další už rychlé. Když EasyOCR není nainstalované nebo selže, spadne to
# automaticky zpět na Tesseract.
_easyocr_reader = None
_easyocr_nedostupne = False

# Striktní režim: když text nesedí na nikoho z uzavřeného seznamu ZNAMI_LIDE,
# vrátí se PRÁZDNÉ jméno místo obecné extrakce z dokladu. Prázdné pole s výzvou
# k ručnímu doplnění je bezpečnější než sebejistě vyplněné cizí jméno — obecná
# extrakce umí přečíst kterýkoliv doklad, což je při testovacím provozu
# omezeném na dva lidi nežádoucí. Vypnout: OCR_STRICT_WHITELIST=0
STRIKTNI_WHITELIST = os.environ.get("OCR_STRICT_WHITELIST", "1") != "0"


def _ziskej_easyocr():
    global _easyocr_reader, _easyocr_nedostupne
    if _easyocr_reader is not None:
        return _easyocr_reader
    if _easyocr_nedostupne:
        return None
    try:
        import torch
        torch.set_num_threads(1)   # viz poznámka u OMP_NUM_THREADS nahoře
        import easyocr
        # čeština + angličtina (na dokladu jsou oba jazyky), běh na CPU
        _easyocr_reader = easyocr.Reader(["cs", "en"], gpu=False, verbose=False)
        return _easyocr_reader
    except Exception:
        _easyocr_nedostupne = True
        return None


def predehrej():
    """Načte EasyOCR model dopředu, ve vlastním vlákně při startu serveru.

    Bez tohohle by se model načítal líně až při prvním skenu — měřeno 16,9 s.
    Na jevišti je sedmnáctisekundové ticho po prvním „Vyfotit doklad“ nepřijatelné,
    a přitom to není chyba, jen líná inicializace. Selhání ignorujeme: když
    EasyOCR není k dispozici, sken pojede na Tesseractu.
    """
    with _ocr_lock:
        try:
            _ziskej_easyocr()
        except Exception:
            pass


def _orizni_kartu(pil_image):
    """
    Najde v fotce obdélník občanky, srovná perspektivu a vrátí čistý výřez karty
    (nebo None, když se karta spolehlivě nenajde – pak se OCR pustí na originál).

    Proč: telefonem se doklad často vyfotí zdálky, karta zabírá jen část záběru
    a kolem je stůl/klávesnice. EasyOCR pak čte z malého rozmazaného kousku a
    text se rozsype. Oříznutím na kartu a zvětšením na plné rozlišení se čtení
    dramaticky zlepší – teprve tím funguje sken i pro lidi mimo whitelist.
    """
    try:
        import cv2
    except Exception:
        return None
    try:
        img = cv2.cvtColor(np.array(pil_image.convert("RGB")), cv2.COLOR_RGB2BGR)
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.bilateralFilter(gray, 11, 17, 17)
        edged = cv2.Canny(gray, 30, 200)
        edged = cv2.dilate(edged, np.ones((5, 5), np.uint8), iterations=1)
        cnts, _ = cv2.findContours(edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cnts = sorted(cnts, key=cv2.contourArea, reverse=True)[:8]
        plocha = w * h
        for c in cnts:
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            if len(approx) != 4:
                continue
            a = cv2.contourArea(approx)
            # Aspoň 10 % plochy (jinak je to nějaký malý útvar), ne celý rám.
            if not (0.10 * plocha < a < 0.99 * plocha):
                continue
            body = approx.reshape(4, 2).astype("float32")
            s = body.sum(axis=1)
            d = np.diff(body, axis=1)
            tl, br = body[np.argmin(s)], body[np.argmax(s)]
            tr, bl = body[np.argmin(d)], body[np.argmax(d)]
            sirka = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
            vyska = max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
            if vyska < 1:
                continue
            pomer = sirka / vyska
            # Občanka (ID-1) je na šířku, poměr ~1.585. Tolerance kvůli náklonu.
            if not (1.3 < pomer < 1.9):
                continue
            W, H = 1000, 630
            src = np.array([tl, tr, br, bl], dtype="float32")
            dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], dtype="float32")
            M = cv2.getPerspectiveTransform(src, dst)
            warp = cv2.warpPerspective(img, M, (W, H))
            return Image.fromarray(cv2.cvtColor(warp, cv2.COLOR_BGR2RGB))
    except Exception:
        return None
    return None


def _easyocr_boxy(pil_image):
    """
    Vrátí seznam boxů [{text, x1, x2, ycstred, vyska}] z EasyOCR (i se
    souřadnicemi), nebo None když EasyOCR není k dispozici. Souřadnice
    potřebujeme, abychom uměli vzít hodnotu NAPRAVO od popisku na stejném řádku.
    """
    reader = _ziskej_easyocr()
    if reader is None:
        return None
    pil_image = pil_image.convert("RGB")
    # Nejdřív zkusit najít a oříznout samotnou kartu – zdálky vyfocený doklad se
    # tím zvětší na plné rozlišení a text přestane být rozsypaný. Když se karta
    # nenajde, jede se na originál.
    karta = _orizni_kartu(pil_image)
    if karta is not None:
        pil_image = karta
    # Malé/oříznuté obrázky (tiny náhledy, výřezy) EasyOCR čte mizerně – před
    # rozpoznáním je zvětšíme, aby byl text čitelný. Velké fotky nechá být.
    if pil_image.width < 1000:
        faktor = min(5, max(1, round(1200 / max(pil_image.width, 1))))
        if faktor > 1:
            pil_image = pil_image.resize(
                (pil_image.width * faktor, pil_image.height * faktor), Image.LANCZOS
            )
    arr = np.array(pil_image)
    boxy = []
    for bbox, text, _conf in reader.readtext(arr, detail=1, paragraph=False):
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        boxy.append({
            "text":   text.strip(),
            "x1":     min(xs),
            "x2":     max(xs),
            "ycstred": sum(ys) / len(ys),
            "vyska":  max(ys) - min(ys),
        })
    return boxy


def _ocr_tesseract(pil_image):
    try:
        return pytesseract.image_to_string(pil_image, lang="ces")
    except Exception:
        return pytesseract.image_to_string(pil_image)


def rozpoznej_text(pil_image):
    """
    Vrátí (text, engine). Nejdřív zkusí EasyOCR (lokální neuronová síť), a když
    není k dispozici nebo nic nevrátí, použije Tesseract. 'engine' říká, co
    text nakonec přečetlo ('easyocr' / 'tesseract').
    """
    boxy = _easyocr_boxy(pil_image)
    if boxy is not None:
        text = "\n".join(b["text"] for b in boxy).strip()
        if text:
            return text, "easyocr"
    return _ocr_tesseract(pil_image), "tesseract"


import difflib


def _bez_diakritiky(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _norm(s):
    return "".join(ch for ch in _bez_diakritiky(s).upper() if ch.isalpha())


def _podobnost(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


# Hlavičkové/popisné výrazy z české občanky, které NEJSOU jméno – odfiltrujeme je.
# Fuzzy porovnání (ne přesná shoda), aby chytilo i OCR překlepy jako "IDENTLTY"
# (IDENTITY) nebo "COCUMENT" (DOCUMENT) – přesně tyhle zkomoleniny se dřív
# omylem braly za jméno, protože se nerovnaly žádnému stopslovu doslovně.
_STOPWORDS = (
    "CESKA", "REPUBLIKA", "CZECH", "IDENTITY", "CARD", "OBCANSKY", "PRUKAZ",
    "PRIJMENI", "SURNAME", "SVANAME", "JMENO", "GIVEN", "NAME", "NAMES",
    "NAROZENI", "DATE", "BIRTH", "PLACE", "OF", "THE", "AND",
    "POHLAVI", "SEX", "OBCANSTVI", "NATIONALITY", "STATNI",
    "PLATNOST", "VALIDITY", "CISLO", "NUMBER", "DOKLADU", "RODNE",
    "PERSONAL", "TRVALY", "POBYT", "ADDRESS", "PROMO", "TYP", "TYPE",
    "DOCUMENT", "NO", "AUTHORITY", "STROJOVE", "MISTO", "MRZ",
)

# Značky, kde na občance končí jméno a začínají další údaje (datum/místo narození).
# Jména bereme jen z části PŘED nimi, aby se nepletlo místo narození (např. CHEB).
_HRANICE_RE = re.compile(r'NAROZEN|BIRTH|POHLAV|\d{2}[.\-/ ]\d{2}[.\-/ ]\d{2,4}', re.IGNORECASE)


def _je_stopslovo(token):
    """
    Je token (i zkomolený) hlavičkový/popisný výraz, a tedy NIKDY ne jméno?
    Práh 0.8 – skutečné OCR překlepy hlavičky mají skóre ~0.87 (IDENTLTY vs
    IDENTITY, COCUMENT vs DOCUMENT), zatímco běžná jména jim jsou podobná jen
    náhodně a mnohem míň (ELIŠKA vs ČESKÁ ~0.73) – 0.8 je bezpečně mezi tím.
    """
    n = _norm(token)
    if not n:
        return False
    if n in ("CZ", "EU"):   # krátké kódy vlajky/země, ne jméno
        return True
    return max(_podobnost(n, s) for s in _STOPWORDS) >= 0.8


def _je_jmeno_token(token):
    """
    Vypadá token jako jméno? Aspoň 3 znaky (žádné 2písmenné kódy jako "CZ"),
    samá písmena, a NENÍ to (ani zkomolený) hlavičkový/popisný výraz.
    """
    if len(token) < 3:
        return False
    if any(ch.isdigit() for ch in token):
        return False
    if _je_stopslovo(token):
        return False
    return True


def extrahuj_jmeno(text):
    """
    Extrahuje (jméno, příjmení) z OCR textu české občanky.

    Strategie v pořadí spolehlivosti:
      1) Kotvení podle klíčových slov Příjmení/Surname a Jméno/Given (funguje,
         když jsou popisky aspoň trochu čitelné).
      2) VELKÁ jména – česká občanka tiskne jméno i příjmení verzálkami (např.
         NOVÁK JAN). Vezmeme první dva „jméno-like" tokeny z části PŘED údaji o
         narození; podle rozvržení občanky je první příjmení, druhé jméno.
      3) Klasická kapitalizovaná slova (Jan Novák) – pro ručně psaný/jiný text.
    """
    # Strategie 1: fuzzy hledání klíčových slov (funguje i na zkomolené OCR)
    prijmeni_re = re.compile(
        r'(?:p[rř][íi]jmen[íi]|surname|svaname)[^A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]*'
        r'([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽa-záčďéěíňóřšťúůýž\-]+)',
        re.IGNORECASE
    )
    jmeno_re = re.compile(
        r'(?:jm[eé]no|given\s*names?|grvex\s*names?|given)[^A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]*'
        r'([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽa-záčďéěíňóřšťúůýž\-]+)',
        re.IGNORECASE
    )

    mp = prijmeni_re.search(text)
    mj = jmeno_re.search(text)

    prijmeni_val = mp.group(1).strip() if mp else ""
    jmeno_val    = mj.group(1).strip() if mj else ""

    if jmeno_val and prijmeni_val and _je_jmeno_token(jmeno_val) and _je_jmeno_token(prijmeni_val):
        return jmeno_val, prijmeni_val

    # Strategie 2: VELKÁ jména z části před údaji o narození
    # (na občance je pořadí: PŘÍJMENÍ, pak JMÉNO)
    hranice = _HRANICE_RE.search(text)
    hlava = text[:hranice.start()] if hranice else text
    velka_re = re.compile(r'[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]{2,}')
    velke_tokeny = [t for t in velka_re.findall(hlava) if _je_jmeno_token(t)]
    if len(velke_tokeny) >= 2:
        return velke_tokeny[1], velke_tokeny[0]  # (jméno, příjmení)

    # Strategie 3: klasická kapitalizovaná slova (Jan Novák)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    vzor  = re.compile(r'[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]{1,}')
    for line in lines:
        if re.search(r'\d{5,}', line): continue
        slova = [s for s in vzor.findall(line) if _je_jmeno_token(s)]
        if len(slova) >= 2:
            return slova[0], slova[1]

    vsechna = []
    for line in lines:
        if re.search(r'\d{5,}', line): continue
        vsechna.extend(s for s in vzor.findall(line) if _je_jmeno_token(s))
    if len(vsechna) >= 2:
        return vsechna[0], vsechna[1]

    # Poslední záchrana: jedno VELKÉ jméno bez páru (aspoň něco doplníme)
    if len(velke_tokeny) == 1:
        return "", velke_tokeny[0]

    return "", ""


# ── Cílená extrakce jen PŘÍJMENÍ a JMÉNA podle rozvržení občanky ─────────────────
# Na české občance je popisek vlevo a hodnota vpravo:
#     PŘÍJMENÍ / SURNAME        SVOBODA
#     JMÉNO / GIVEN NAMES       ELIŠKA
# Popisky ale OCR často zkomolí (PŘÍJMENÍ -> "PAUMENI", SURNAME -> "suRkAME"),
# proto je porovnáváme FUZZY (podobnost), ne na přesnou shodu.
#
# DŮLEŽITÉ: jméno/příjmení hledáme JEN v okně mezi koncem hlavičky dokladu
# (CZ / OBČANSKÝ PRŮKAZ / IDENTITY CARD / ČÍSLO DOKLADU...) a začátkem dalších
# údajů (datum narození / pohlaví / ...). Mimo tohle okno se nikdy nehledá –
# proto se už nemůže stát, že se za jméno vezme text z hlavičky dokladu.
# A když se v tomhle okně nenajde ŽÁDNÝ jistý popisek, radši se vrátí prázdno
# než vymyšlená hodnota – prázdné pole s ruční opravou je vždycky lepší
# než sebejistě špatný údaj.

# Slova, která jsou POPISEK (ne hodnota). Fuzzy porovnáváme proti nim.
_LABEL_WORDS = ("PRIJMENI", "SURNAME", "JMENO", "GIVEN", "GIVENNAMES", "NAMES", "NAME")
_KLICE_PRIJMENI = ("PRIJMENI", "SURNAME")
_KLICE_JMENO = ("JMENO", "GIVEN", "GIVENNAMES", "NAMES")

# Popisky HLAVIČKY dokladu – vše na/nad touto úrovní je mimo hru.
_HLAVICKA_POPISKY = (
    "CESKA", "REPUBLIKA", "CZECH", "IDENTITY", "CARD", "OBCANSKY", "PRUKAZ",
    "CISLO", "DOKLADU", "DOCUMENT", "NUMBER",
)


def _slova(text):
    return re.findall(r"[^\W\d_]+", text, re.UNICODE)


def _label_skore(slovo):
    """Nejlepší podobnost slova k některému popisku Příjmení/Jméno (0..1)."""
    n = _norm(slovo)
    if not n:
        return 0.0
    return max(_podobnost(n, lw) for lw in _LABEL_WORDS)


# Jen 1 slovo. Druhé a třetí slovo bývá skoro vždy OCR šum ze zašuměné/
# nasvícené fotky (nekoliduje s žádným popiskem, takže se nedá odfiltrovat) –
# raději obětujeme vzácná dvouslovná jména než abychom soustavně lepili
# náhodný šum za správně přečtenou hodnotu.
_MAX_SLOV_HODNOTY = 1


def _hodnota_radku(rb):
    """
    Vrátí hodnotu (jméno-like slova) z jednoho řádku boxů seřazených podle x.

    Popisek bývá rozdělený OCR do VÍCE boxů/slov (např. box 'Jmeno' + box
    'GIVEN NAMes'), a navíc bývá zkomolený NEROVNOMĚRNĚ – první slovo popisku
    může být přečtené tak špatně, že samo o sobě neprojde žádným prahem
    (např. „PŘÍJMENÍ" -> „Pauveni", podobnost jen 0.53), zatímco druhé slovo
    stejného popisku je čitelnější („SURNAME" -> „Suanamg", podobnost 0.71).
    Lineární „skoč přes první slova, co vypadají jako popisek" by se tu
    zastavilo hned na první slovo a zbytek popisku by omylem vzalo za hodnotu.
    Proto najdeme NEJLEPŠÍ shodu s popiskem KDEKOLIV v řádku a přeskočíme
    všechno až po ni – skutečný popisek má vždy vyšší skóre než náhodná
    podobnost hodnoty (ověřeno na reálných i referenčních fotkách).
    """
    slova = []
    for b in rb:
        slova.extend(_slova(b["text"]))

    skore = [_label_skore(w) for w in slova]
    i = 0
    if skore:
        maxskore = max(skore)
        if maxskore >= 0.55:
            # Popisek bývá dvouslovný (Příjmení + Surname) a obě slova mají
            # podobně vysoké skóre – vezmeme POSLEDNÍ slovo blízko maxima
            # (tolerance 0.05), ne jen tu úplně nejlepší shodu, aby se
            # nepřeskočilo jen první z dvojice a druhé nezůstalo v hodnotě.
            kandidati = [k for k, s in enumerate(skore) if s >= maxskore - 0.05]
            i = max(kandidati) + 1

    # Popisek je občas zkomolený NEROVNOMĚRNĚ – jedno jeho slovo může zůstat
    # za skokem výše (např. "GIVEN" se přeskočí, ale "Nales" za NAMES ne).
    # Dokud jsme NEZAČALI sbírat skutečnou hodnotu, takové zbytky popisku jen
    # PŘESKOČÍME (nezastavujeme se) – teprve jakmile máme první opravdové
    # jméno-slovo, další nejméně-jméno-podobné slovo znamená konec hodnoty
    # (typicky začátek jiného pole na slitém/nakloněném řádku).
    toks = []
    for w in slova[i:]:
        if _je_jmeno_token(w):
            toks.append(w)
            if len(toks) >= _MAX_SLOV_HODNOTY:
                break
        elif toks:
            break
    return toks


def _skore_label(boxy_radku, klice):
    """Nejlepší podobnost některého slova v řádku k dané skupině popisků."""
    best = 0.0
    for b in boxy_radku:
        for w in _slova(b["text"]):
            n = _norm(w)
            if n:
                best = max(best, max(_podobnost(n, k) for k in klice))
    return best


def _klasifikuj_radek(boxy_radku):
    """
    Vrátí (je_prijmeni, je_jmeno). Popisek 'PŘÍJMENÍ' je bohužel podobný slovu
    'JMÉNO' (obsahuje 'JMEN'), proto řádek zařadíme podle SILNĚJŠÍHO matche –
    ne jen podle prahu, aby se příjmení nepletlo se jménem.
    """
    sp = _skore_label(boxy_radku, _KLICE_PRIJMENI)
    sj = _skore_label(boxy_radku, _KLICE_JMENO)
    je_prijmeni = sp >= 0.55 and sp >= sj
    je_jmeno    = sj >= 0.55 and sj > sp
    return je_prijmeni, je_jmeno


def _je_radek_hlavicka(boxy_radku):
    """Obsahuje řádek (i zkomoleně) popisek hlavičky dokladu (CZ, PRŮKAZ, ČÍSLO DOKLADU...)?"""
    return _skore_label(boxy_radku, _HLAVICKA_POPISKY) >= 0.7


# Popisky polí ZA jménem (datum narození, pohlaví, ...) – kde okno pro hledání
# jména KONČÍ. Záměrně BEZ popisků jména/příjmení a bez hlavičkových slov jako
# ČÍSLO/DOKLADU – ta se řeší zvlášť, aby se za hranici omylem nepovažoval
# samotný řádek se jménem.
_RADEK_HRANICE_POPISKY = (
    "DATUM", "NAROZENI", "DATE", "BIRTH", "POHLAVI", "SEX",
    "STATNI", "OBCANSTVI", "NATIONALITY", "PLATNOST", "VALIDITY",
    "RODNE", "TRVALY", "POBYT", "MISTO", "PLACE", "STROJOVE", "AUTHORITY",
)


def _je_radek_hranice(boxy_radku):
    """Obsahuje řádek (i zkomoleně) popisek pole ZA jménem (datum, pohlaví, ...)?"""
    return _skore_label(boxy_radku, _RADEK_HRANICE_POPISKY) >= 0.72


def _titulek(s):
    """VELKÁ jména z dokladu převede na čitelný tvar: 'SVOBODA' -> 'Svoboda'."""
    return " ".join((w[:1].upper() + w[1:].lower()) if w else w for w in s.split())


def _seskup_radky(boxy):
    """Seskupí boxy do řádků podle svislé polohy (odshora dolů)."""
    radky = []
    for b in sorted(boxy, key=lambda b: b["ycstred"]):
        umisteno = False
        for r in radky:
            if abs(b["ycstred"] - r["y"]) <= 0.7 * max(b["vyska"], r["vyska"], 1):
                r["boxy"].append(b)
                r["vyska"] = max(r["vyska"], b["vyska"])
                umisteno = True
                break
        if not umisteno:
            radky.append({"y": b["ycstred"], "vyska": b["vyska"], "boxy": [b]})
    return radky


def _jmeno_prijmeni_z_boxu(boxy):
    """
    Vytáhne (jmeno, prijmeni) z boxů se souřadnicemi – ale JEN v okně mezi
    koncem hlavičky dokladu a začátkem dalších údajů (datum narození, pohlaví...).
    Cokoliv nad/pod tímhle oknem se do jména nikdy nedostane – proto se sem
    nemůže priplést text hlavičky dokladu ("CZ IDENTITY CARD" apod.).

    Když se v okně nenajde ŽÁDNÝ jistý popisek Příjmení/Jméno, vrátí prázdno
    – nehádá se z náhodných řádků, protože špatně vymyšlená hodnota je horší
    než prázdné pole s výzvou k ruční opravě.
    """
    radky = []
    for r in _seskup_radky(boxy):
        rb = sorted(r["boxy"], key=lambda b: b["x1"])
        je_prijm, je_jmeno = _klasifikuj_radek(rb)
        radky.append({
            "y":        r["y"],
            "hod":      _hodnota_radku(rb),
            "prijm":    je_prijm,
            "jmeno":    je_jmeno,
            "hlavicka": _je_radek_hlavicka(rb),
            "hranice":  _je_radek_hranice(rb),
        })
    radky.sort(key=lambda r: r["y"])

    # Konec hlavičky = konec SOUVISLÉHO bloku hlavičkových řádků odshora (ne
    # kdekoli na kartě!). "ČESKÁ REPUBLIKA" je na dokladu i podruhé dole u
    # "Státní občanství" – kdybychom brali poslední výskyt kdekoliv, okno by se
    # posunulo až za jméno a jméno by úplně vypadlo z hledání.
    konec_hlavicky = None
    for r in radky:
        if r["hlavicka"]:
            konec_hlavicky = r["y"]
        else:
            break

    hranice = [r["y"] for r in radky if r["hranice"]]
    zacatek_hranice = min(hranice) if hranice else None

    okno = [
        r for r in radky
        if (konec_hlavicky is None or r["y"] > konec_hlavicky)
        and (zacatek_hranice is None or r["y"] < zacatek_hranice)
    ]

    prijmeni_radek = next((r for r in okno if r["prijm"]), None)
    jmeno_radek    = next((r for r in okno if r["jmeno"]), None)

    # Bez ANI JEDNOHO jistého popisku v okně nemá smysl cokoliv hádat.
    if prijmeni_radek is None and jmeno_radek is None:
        return "", ""

    prijmeni = " ".join(prijmeni_radek["hod"]) if prijmeni_radek and prijmeni_radek["hod"] else ""
    jmeno    = " ".join(jmeno_radek["hod"]) if jmeno_radek and jmeno_radek["hod"] else ""

    # Poziční doplnění chybějícího pole – jen když je v okně PŘESNĚ jeden další
    # řádek s hodnotou (žádná nejednoznačnost mezi víc kandidáty).
    ostatni = [r for r in okno if r["hod"] and r is not prijmeni_radek and r is not jmeno_radek]
    if len(ostatni) == 1:
        if not prijmeni and jmeno_radek is not None and ostatni[0]["y"] < jmeno_radek["y"]:
            prijmeni = " ".join(ostatni[0]["hod"])
        elif not jmeno and prijmeni_radek is not None and ostatni[0]["y"] > prijmeni_radek["y"]:
            jmeno = " ".join(ostatni[0]["hod"])

    return jmeno, prijmeni


def precti_doklad(pil_image):
    """
    Hlavní funkce: vrátí (jmeno, prijmeni, text, engine).

    Nejdřív zkusí porovnat celý OCR text proti uzavřenému seznamu ZNÁMÝCH lidí
    (viz uroci_znamou_osobu) – to je spolehlivější než obecná extrakce, protože
    stačí, aby bylo čitelné JMÉNO NEBO PŘÍJMENÍ (fuzzy) kdekoli v textu, a
    zapíše se rovnou správná kanonická hodnota, ne to, co OCR doslova přečetlo.

    Když žádný známý člověk s jistotou nesedí, spadne na obecnou extrakci:
    s EasyOCR cílí PŘESNĚ na pole PŘÍJMENÍ a JMÉNO podle rozvržení občanky,
    v okně mezi hlavičkou dokladu a dalšími údaji (viz _jmeno_prijmeni_z_boxu).
    Když si tímhle způsobem není jistý, vrátí prázdné jméno/příjmení – ZÁMĚRNĚ
    nepadá na hádání z celého textu (to je přesně ten mechanismus, který dřív
    místo jména vracel útržky hlavičky dokladu). Prázdné pole s výzvou k ruční
    opravě je vždycky lepší než sebejistě špatný údaj.
    """
    with _ocr_lock:
        return _precti_doklad_bez_zamku(pil_image)


def _precti_doklad_bez_zamku(pil_image):
    boxy = _easyocr_boxy(pil_image)
    if boxy is not None:
        text = "\n".join(b["text"] for b in boxy).strip()
        znamy_jmeno, znamy_prijmeni = uroci_znamou_osobu(text)
        if znamy_jmeno:
            return znamy_jmeno, znamy_prijmeni, text, "easyocr"
        if STRIKTNI_WHITELIST:
            return "", "", text, "easyocr"
        jmeno, prijmeni = _jmeno_prijmeni_z_boxu(boxy)
        return _titulek(jmeno), _titulek(prijmeni), text, "easyocr"

    text = _ocr_tesseract(pil_image)
    znamy_jmeno, znamy_prijmeni = uroci_znamou_osobu(text)
    if znamy_jmeno:
        return znamy_jmeno, znamy_prijmeni, text, "tesseract"
    if STRIKTNI_WHITELIST:
        return "", "", text, "tesseract"
    j, p = extrahuj_jmeno(text)
    return _titulek(j), _titulek(p), text, "tesseract"


# ── Uzavřený seznam ZNÁMÝCH lidí (testovací provoz) ──────────────────────────────
# Než je obecná extrakce dost spolehlivá na jakoukoliv občanku, porovnáváme
# místo toho text proti PŘESNĚ TĚMTO lidem – stačí čitelné jméno NEBO příjmení
# kdekoli v OCR textu a zapíše se rovnou správná (kanonická) hodnota. Přidat
# dalšího člověka = přidat řádek sem.
ZNAMI_LIDE = []


def _nejlepsi_shoda_v_textu(text, cil):
    """Nejlepší podobnost libovolného slova v textu k cílovému slovu (0..1)."""
    cil_n = _norm(cil)
    nej = 0.0
    for w in _slova(text):
        n = _norm(w)
        if n:
            nej = max(nej, _podobnost(n, cil_n))
    return nej


def uroci_znamou_osobu(text):
    """
    Vrátí (jmeno, prijmeni) známé osoby z OCR textu, nebo (None, None), když
    si nejsme dost jistí (aspoň průměrně slušná shoda u obou slov A jasný
    náskok před druhým kandidátem – jinak radši nic nevracet).
    """
    if not text:
        return None, None
    nej_idx, nej_skore, druhe_skore = -1, 0.0, 0.0
    for i, osoba in enumerate(ZNAMI_LIDE):
        skore = (_nejlepsi_shoda_v_textu(text, osoba["jmeno"])
                 + _nejlepsi_shoda_v_textu(text, osoba["prijmeni"]))
        if skore > nej_skore:
            druhe_skore = nej_skore
            nej_skore = skore
            nej_idx = i
        elif skore > druhe_skore:
            druhe_skore = skore
    if nej_idx >= 0 and nej_skore >= 1.1 and nej_skore - druhe_skore >= 0.2:
        osoba = ZNAMI_LIDE[nej_idx]
        return osoba["jmeno"], osoba["prijmeni"]
    return None, None

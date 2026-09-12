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

# Velká a malá písmena latinky, která se smí objevit ve jméně na dokladu:
# česká + německá diakritika. Drží se na JEDNOM místě, ať přidání dalšího
# jazyka (nebo znaku) neznamená projít a upravit každý regex zvlášť. Dřív byly
# znakové třídy rozepsané v každém vzoru a německé ä/ö/ü/ß v nich chyběly, takže
# i správně přečtené „MÜLLER" se v Tesseract větvi rozsekalo na „M" + „LLER".
# Pozn.: ß nemá běžně používanou velkou variantu a OCR ho i uvnitř verzálek
# vrací malé (WEIß), proto je i mezi „velkými" znaky.
_VELKA = "A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽÄÖÜßẞ"
_MALA = "a-záčďéěíňóřšťúůýžäöüß"

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
# vrátí se PRÁZDNÉ jméno místo obecné extrakce z dokladu. VÝCHOZÍ stav je teď
# VYPNUTO (obecná extrakce čte jméno z libovolného dokladu) — uzavřený seznam
# ZNAMI_LIDE se pro běžný provoz nepoužívá. Striktní režim jde znovu zapnout
# přes OCR_STRICT_WHITELIST=1 (jen pro omezené testovací demo na známé osoby).
STRIKTNI_WHITELIST = os.environ.get("OCR_STRICT_WHITELIST", "0") == "1"


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
        # čeština + němčina + angličtina (na dokladech bývají dva i tři jazyky),
        # běh na CPU. 'de' přidává znaky ä ö ü ß – bez něj se ostré ß čte špatně
        # (WEIß -> WEIB); Ü zvládá model latin_g2 i bez toho. Za běhu je rozdíl
        # zanedbatelný, jen se o kousek prodlouží první načtení modelu.
        _easyocr_reader = easyocr.Reader(["cs", "de", "en"], gpu=False, verbose=False)
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
    # zdravotní karta / EHIC – „pojištěnce"/„pojišťovna" jsou fuzzy podobné
    # příjmení „Pistora"; bez odfiltrování whitelist přiřadil cizí kartu známé
    # osobě (viz uroci_znamou_osobu). Záměrně BEZ „KARTA/KARTY" – to je moc
    # blízko jménu „Marta".
    "POJISTENEC", "POJISTENCE", "POJISTOVNA", "POJISTOVNY", "POJISTENI",
    "ZDRAVOTNI", "ZDRAVOTNIHO", "EVROPSKY", "EVROPSKEHO", "INSTITUCE",
    "VSEOBECNA", "EHIC",
    # zkratky českých zdravotních pojišťoven – na kartě stojí samostatně a bez
    # nich by se braly za jméno (klasicky „VZP" vyšlo jako příjmení).
    "VZP", "VOZP", "CPZP", "OZP", "ZPMV", "RBP", "ZPS",
    # řidičák
    "RIDICSKY", "DRIVING", "LICENCE", "LICENSE", "PERMIS", "SKUPINA", "CATEGORY",
    # německé doklady (Name/Vorname se řeší i jako popisky v _CFG níž)
    "BUNDESREPUBLIK", "DEUTSCHLAND", "PERSONALAUSWEIS", "VORNAME",
    "GEBURTSNAME", "GEBURTSDATUM", "GEBURTSORT", "FUHRERSCHEIN",
    "STAATSANGEHORIGKEIT", "GULTIG",
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
        rf'(?:p[rř][íi]jmen[íi]|surname|svaname)[^{_VELKA}]*'
        rf'([{_VELKA}][{_VELKA}{_MALA}\-]+)',
        re.IGNORECASE
    )
    jmeno_re = re.compile(
        rf'(?:jm[eé]no|given\s*names?|grvex\s*names?|given|vorname)[^{_VELKA}]*'
        rf'([{_VELKA}][{_VELKA}{_MALA}\-]+)',
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
    velka_re = re.compile(rf'[{_VELKA}]{{2,}}')
    velke_tokeny = [t for t in velka_re.findall(hlava) if _je_jmeno_token(t)]
    if len(velke_tokeny) >= 2:
        return velke_tokeny[1], velke_tokeny[0]  # (jméno, příjmení)

    # Strategie 3: klasická kapitalizovaná slova (Jan Novák)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    vzor  = re.compile(rf'[{_VELKA}][{_MALA}]{{1,}}')
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


def _label_skore(slovo, label_words):
    """Nejlepší podobnost slova k některému popisku Příjmení/Jméno (0..1)."""
    n = _norm(slovo)
    if not n:
        return 0.0
    return max(_podobnost(n, lw) for lw in label_words)


# Jen 1 slovo. Druhé a třetí slovo bývá skoro vždy OCR šum ze zašuměné/
# nasvícené fotky (nekoliduje s žádným popiskem, takže se nedá odfiltrovat) –
# raději obětujeme vzácná dvouslovná jména než abychom soustavně lepili
# náhodný šum za správně přečtenou hodnotu.
_MAX_SLOV_HODNOTY = 1


def _hodnota_radku(rb, cfg):
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

    skore = [_label_skore(w, cfg["label_words"]) for w in slova]
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


def _klasifikuj_radek(boxy_radku, cfg):
    """
    Vrátí (je_prijmeni, je_jmeno). Nejdřív číselné markery pole (řidičák 1./2.,
    EHIC 3./4.) – ty jsou jednoznačné. Když nejsou, fuzzy popisky: 'PŘÍJMENÍ' je
    bohužel podobný slovu 'JMÉNO' (obsahuje 'JMEN'), proto řádek zařadíme podle
    SILNĚJŠÍHO matche – ne jen podle prahu, aby se příjmení nepletlo se jménem.
    """
    mark = _cislo_markery(boxy_radku)
    if mark & set(cfg["cislo_prijmeni"]):
        return True, False
    if mark & set(cfg["cislo_jmeno"]):
        return False, True
    sp = _skore_label(boxy_radku, cfg["klice_prijmeni"])
    sj = _skore_label(boxy_radku, cfg["klice_jmeno"])
    je_prijmeni = sp >= 0.55 and sp >= sj
    je_jmeno    = sj >= 0.55 and sj > sp
    return je_prijmeni, je_jmeno


def _je_radek_hlavicka(boxy_radku, cfg):
    """Obsahuje řádek (i zkomoleně) popisek hlavičky dokladu (CZ, PRŮKAZ, ČÍSLO DOKLADU...)?"""
    return _skore_label(boxy_radku, cfg["hlavicka"]) >= 0.7


# Popisky polí ZA jménem (datum narození, pohlaví, ...) – kde okno pro hledání
# jména KONČÍ. Záměrně BEZ popisků jména/příjmení a bez hlavičkových slov jako
# ČÍSLO/DOKLADU – ta se řeší zvlášť, aby se za hranici omylem nepovažoval
# samotný řádek se jménem.
_RADEK_HRANICE_POPISKY = (
    "DATUM", "NAROZENI", "DATE", "BIRTH", "POHLAVI", "SEX",
    "STATNI", "OBCANSTVI", "NATIONALITY", "PLATNOST", "VALIDITY",
    "RODNE", "TRVALY", "POBYT", "MISTO", "PLACE", "STROJOVE", "AUTHORITY",
)


def _je_radek_hranice(boxy_radku, cfg):
    """Obsahuje řádek (i zkomoleně) popisek pole ZA jménem (datum, pohlaví, ...)?"""
    return _skore_label(boxy_radku, cfg["hranice"]) >= 0.72


def _radek_ma_data(boxy_radku):
    """Vypadá řádek jako ÚDAJ (ne jméno)? Tj. obsahuje datum nebo delší číslo
    (číslo pojištěnce/karty, datum narození/platnosti). Slouží jako spodní
    hranice okna se jménem u zdravotních karet, kde jméno nemá popisek."""
    t = " ".join(b["text"] for b in boxy_radku)
    if re.search(r'\d{2}[.\-/ ]\d{2}[.\-/ ]\d{2,4}', t):   # datum
        return True
    if re.search(r'\d{4,}', t):                            # delší číslo
        return True
    return False


# ── Typ dokladu + sady popisků podle typu ────────────────────────────────────────
# Extrakce jména cílí na pole PŘÍJMENÍ/JMÉNO podle rozvržení, jenže popisky se
# doklad od dokladu liší (občanka: „Příjmení/Surname"; řidičák: číslovaná pole
# „1./2."; němčina: „Name/Vorname"; EHIC: „3./4."). Typ se pozná SÁM z hlavičky
# (návštěvník nic nevybírá) a podle něj se vybere sada popisků. Když si nejsme
# jistí, spadne to na občanku – historicky odladěné, výchozí chování.
TYP_OBCANKA = "obcanka"
TYP_RIDICAK = "ridicak"
TYP_ZDRAVOTNI = "zdravotni"          # průkaz pojištěnce / EHIC
TYP_PERSONALAUSWEIS = "personalausweis"


def rozpoznej_typ_dokladu(text):
    """Určí typ dokladu z klíčových slov hlavičky. _norm slepí text do jednoho
    řetězce velkých písmen bez diakritiky a mezer, takže hledáme podřetězce."""
    n = _norm(text)

    def ma(*frags):
        return any(f in n for f in frags)

    if ma("RIDICSKYPRUKAZ", "DRIVINGLICENCE", "FUHRERSCHEIN", "PERMISDECONDUIRE"):
        return TYP_RIDICAK
    if ma("ZDRAVOTNIHOPOJISTENI", "PRUKAZPOJISTENCE", "POJISTOVNA",
          "POJISTENCE", "EVROPSKYPRUKAZ", "EHIC"):
        return TYP_ZDRAVOTNI
    if ma("PERSONALAUSWEIS", "BUNDESREPUBLIKDEUTSCHLAND"):
        return TYP_PERSONALAUSWEIS
    return TYP_OBCANKA


# Sady popisků pro jednotlivé typy. Klíče:
#   klice_prijmeni / klice_jmeno   – slovní popisky polí (fuzzy)
#   cislo_prijmeni / cislo_jmeno   – číselné markery pole (řidičák 1./2., EHIC 3./4.)
#   label_words                    – všechna slova popisků (co se v hodnotě přeskočí)
#   hlavicka                       – slova hlavičky (konec bloku = konec hlavičky)
#   hranice                        – popisky polí ZA jménem (kde okno pro jméno končí)
#
# POZOR u němčiny: „Name" = PŘÍJMENÍ, „Vorname" = JMÉNO. Proto u personalausweisu
# NENÍ „NAME/NAMES" mezi klíči jména – jinak by se MÜLLER (Name) přiřadil jako
# křestní jméno (přesně tahle tichá záměna se dřív dělala).
_CFG = {
    TYP_OBCANKA: {
        "klice_prijmeni": _KLICE_PRIJMENI,
        "klice_jmeno":    _KLICE_JMENO,
        "cislo_prijmeni": (),
        "cislo_jmeno":    (),
        "label_words":    _LABEL_WORDS,
        "hlavicka":       _HLAVICKA_POPISKY,
        "hranice":        _RADEK_HRANICE_POPISKY,
    },
    TYP_RIDICAK: {
        "klice_prijmeni": ("PRIJMENI", "SURNAME", "NAME"),
        "klice_jmeno":    ("JMENO", "GIVEN", "GIVENNAMES", "NAMES", "VORNAME"),
        "cislo_prijmeni": ("1",),
        "cislo_jmeno":    ("2",),
        "label_words":    ("PRIJMENI", "SURNAME", "JMENO", "GIVEN", "GIVENNAMES",
                           "NAMES", "NAME", "VORNAME"),
        "hlavicka":       ("CESKA", "REPUBLIKA", "RIDICSKY", "PRUKAZ", "DRIVING",
                           "LICENCE", "FUHRERSCHEIN"),
        "hranice":        ("DATUM", "NAROZENI", "DATE", "BIRTH", "MISTO", "PLACE",
                           "PLATNOST", "VALIDITY", "VYDAL", "AUTHORITY",
                           "SKUPINA", "CATEGORY"),
    },
    TYP_ZDRAVOTNI: {
        "klice_prijmeni": ("PRIJMENI", "SURNAME", "NAME"),
        "klice_jmeno":    ("JMENO", "GIVEN", "GIVENNAMES", "NAMES", "VORNAME"),
        "cislo_prijmeni": ("3",),
        "cislo_jmeno":    ("4",),
        "label_words":    ("PRIJMENI", "SURNAME", "JMENO", "GIVEN", "GIVENNAMES",
                           "NAMES", "NAME"),
        "hlavicka":       ("EVROPSKY", "PRUKAZ", "ZDRAVOTNIHO", "POJISTENI",
                           "POJISTOVNA", "POJISTENCE", "VSEOBECNA", "EHIC"),
        "hranice":        ("DATUM", "NAROZENI", "OSOBNI", "IDENTIFIKACNI",
                           "INSTITUCE", "CISLO", "KARTY", "PLATNOST", "EXPIRACE"),
        # Přední strana průkazu pojištěnce tiskne jméno POHROMADĚ bez popisků
        # („NOVÁK JAN"). Když se v okně nenajde žádný popisek Příjmení/Jméno,
        # vezme se jméno pozičně z tohoto bloku (viz _jmeno_prijmeni_z_boxu).
        "jmeno_pohromade": True,
    },
    TYP_PERSONALAUSWEIS: {
        "klice_prijmeni": ("NAME", "SURNAME", "GEBURTSNAME"),
        "klice_jmeno":    ("VORNAME", "GIVENNAMES", "GIVEN"),   # ZÁMĚRNĚ bez NAME/NAMES
        "cislo_prijmeni": (),
        "cislo_jmeno":    (),
        "label_words":    ("NAME", "SURNAME", "GEBURTSNAME", "VORNAME", "GIVEN",
                           "GIVENNAMES", "NAMES"),
        "hlavicka":       ("BUNDESREPUBLIK", "DEUTSCHLAND", "PERSONALAUSWEIS",
                           "IDENTITY", "CARD"),
        "hranice":        ("GEBURTSDATUM", "GEBURTSORT", "STAATSANGEHORIGKEIT",
                           "DATE", "BIRTH", "GULTIG"),
    },
}


def _cislo_markery(boxy_radku):
    """Čísla polí na začátku boxů řádku (řidičák 1./2., EHIC 3./4.). _slova()
    číslice zahazuje, proto markery čteme ze surového textu boxu.

    Rozlišujeme marker pole od data/čísla: za tečkou/závorkou markeru NÁSLEDUJE
    text (např. „1. NOVÁK"), kdežto u data „1.1.1990" a čísla karty následuje
    další číslice – tam marker nevzniká. Bere i samostatné číslo v boxu (OCR
    tečku občas ztratí)."""
    out = set()
    for b in boxy_radku:
        t = b["text"].strip()
        m = re.match(r'^(\d{1,2})[.)](?!\s*\d)', t)   # „1." / „2)" + NE-číslice
        if m:
            out.add(m.group(1))
        elif re.match(r'^\d{1,2}$', t):               # samostatné číslo v boxu
            out.add(t)
    return out


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


def _jmeno_prijmeni_z_boxu(boxy, cfg):
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
        je_prijm, je_jmeno = _klasifikuj_radek(rb, cfg)
        radky.append({
            "y":        r["y"],
            "boxy":     rb,
            "hod":      _hodnota_radku(rb, cfg),
            "prijm":    je_prijm,
            "jmeno":    je_jmeno,
            "hlavicka": _je_radek_hlavicka(rb, cfg),
            "hranice":  _je_radek_hranice(rb, cfg),
        })
    radky.sort(key=lambda r: r["y"])

    # Zdravotní karty (EHIC / průkaz pojištěnce): jméno tu bývá BEZ spolehlivých
    # popisků a hlavičkové slovo „pojištění/pojišťovna" se fuzzy plete s
    # příjmením (POJISTOVNA ~ PISTORA), takže popiskové kotvení tu i přiřkne
    # nesmysl. Proto zakotvíme na řádku hlavičky ("EVROPSKÝ PRŮKAZ ZDRAVOTNÍHO
    # POJIŠTĚNÍ" / "Průkaz pojištěnce") a vezmeme první dvě jméno-like slova POD
    # ním, dokud nenarazíme na řádek s daty (datum/číslo). Na české kartě je
    # pořadí PŘÍJMENÍ, pak JMÉNO. Řádek hlavičky je vždy silná víceslovná shoda,
    # takže má vyšší skóre než náhodná shoda jednoho příjmení s popiskem.
    if cfg.get("jmeno_pohromade"):
        nej_hl, anchor = 0.0, None
        for r in radky:
            s = _skore_label(r["boxy"], cfg["hlavicka"])
            if s > nej_hl:
                nej_hl, anchor = s, r
        if anchor is not None and nej_hl >= 0.7:
            tokeny = []
            for r in radky:
                if r["y"] <= anchor["y"]:
                    continue
                if r["hranice"] or _radek_ma_data(r["boxy"]):
                    break
                tokeny.extend(w for b in r["boxy"]
                              for w in _slova(b["text"]) if _je_jmeno_token(w))
                if len(tokeny) >= 2:
                    break
            if len(tokeny) >= 2:
                return tokeny[1], tokeny[0]   # (jmeno, prijmeni)
            if len(tokeny) == 1:
                return "", tokeny[0]

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
    # (Zdravotní karty bez popisků řeší header-kotvená větev na začátku funkce.)
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

    Typ dokladu (občanka / řidičák / průkaz pojištěnce / Personalausweis) se
    pozná SÁM z hlavičky (viz rozpoznej_typ_dokladu) a podle něj se vybere sada
    popisků pro extrakci – s EasyOCR cílí PŘESNĚ na pole PŘÍJMENÍ a JMÉNO podle
    rozvržení, v okně mezi hlavičkou dokladu a dalšími údaji (_jmeno_prijmeni_z_boxu).
    Uzavřený seznam ZNÁMÝCH lidí (uroci_znamou_osobu) výsledek jen kanonizuje
    nebo doplní, když si je jistý – už NEporovnává celý text (to dřív přiřazovalo
    cizí karty známým lidem). Když si extrakce není jistá, vrátí prázdno –
    prázdné pole s výzvou k ruční opravě je vždycky lepší než sebejistě špatný
    údaj. Podrobnosti o pořadí a striktním režimu viz _vyhodnot.
    """
    with _ocr_lock:
        return _precti_doklad_bez_zamku(pil_image)


def _precti_doklad_bez_zamku(pil_image):
    boxy = _easyocr_boxy(pil_image)
    if boxy is not None:
        text = "\n".join(b["text"] for b in boxy).strip()
        return _vyhodnot(text, boxy, "easyocr")
    text = _ocr_tesseract(pil_image)
    return _vyhodnot(text, None, "tesseract")


def _vyhodnot(text, boxy, engine):
    """Z OCR textu (a případně boxů) určí (jmeno, prijmeni, text, engine).

    Pořadí je záměrné a opravuje starou chybu, kdy whitelist fuzzy porovnával
    CELÝ text a dokladová slova („pojištěnce" ~ „Pistora") přiřkla cizí kartu
    známé osobě – a to i v ostrém provozu, protože whitelist běžel PŘED
    striktní kontrolou i před extrakcí:

      1) Whitelist (uroci_znamou_osobu) je teď tvrdý – porovnává jen jméno-like
         slova a vyžaduje vysokou shodu OBOU polí zvlášť. Pro známé zaměstnance
         zůstává nejspolehlivější (vrací kanonický pravopis).
      2) Striktní režim pustí ven jen osobu ze seznamu, jinak prázdno (žádná
         obecná extrakce) – stejné chování jako dřív.
      3) Volný režim: obecná extrakce cílená na ROZPOZNANÝ TYP dokladu; whitelist
         pak výsledek jen KANONIZUJE nebo DOPLNÍ, ale nepřebije jiné jisté jméno.
    """
    znj, znp = uroci_znamou_osobu(text)

    if STRIKTNI_WHITELIST:
        if znj:
            return znj, znp, text, engine
        return "", "", text, engine

    typ = rozpoznej_typ_dokladu(text)
    if boxy is not None:
        jmeno, prijmeni = _jmeno_prijmeni_z_boxu(boxy, _CFG[typ])
        jmeno, prijmeni = _titulek(jmeno), _titulek(prijmeni)
    else:
        j, p = extrahuj_jmeno(text)
        jmeno, prijmeni = _titulek(j), _titulek(p)

    if znj and (not (jmeno and prijmeni) or _stejna_osoba(jmeno, prijmeni, znj, znp)):
        jmeno, prijmeni = znj, znp
    return jmeno, prijmeni, text, engine


# ── Uzavřený seznam ZNÁMÝCH lidí (testovací provoz) ──────────────────────────────
# Než je obecná extrakce dost spolehlivá na jakoukoliv občanku, porovnáváme
# místo toho text proti PŘESNĚ TĚMTO lidem – stačí čitelné jméno NEBO příjmení
# kdekoli v OCR textu a zapíše se rovnou správná (kanonická) hodnota. Přidat
# dalšího člověka = přidat řádek sem.
ZNAMI_LIDE = []


def _nejlepsi_shoda_v_textu(text, cil):
    """Nejlepší podobnost JMÉNO-podobného slova v textu k cílovému slovu (0..1).

    Hlavičková/popisná a dokladová slova (pojištěnec, pojišťovna, průkaz, ...)
    se do porovnání NEPOUŠTĚJÍ – jinak se náhodně podobají příjmením (klasicky
    „pojištěnce" ~ „Pistora") a whitelist by přiřkl cizí kartu známé osobě.
    """
    cil_n = _norm(cil)
    nej = 0.0
    for w in _slova(text):
        if not _je_jmeno_token(w):
            continue
        n = _norm(w)
        if n:
            nej = max(nej, _podobnost(n, cil_n))
    return nej


def _stejna_osoba(j1, p1, j2, p2):
    """Jsou (j1,p1) a (j2,p2) fuzzy tatáž osoba? Používá se, aby whitelist směl
    jen SROVNAT pravopis toho, co extrakce už našla – ne přepsat jiné jméno."""
    return (_podobnost(_norm(j1), _norm(j2)) >= 0.6 and
            _podobnost(_norm(p1), _norm(p2)) >= 0.6)


def uroci_znamou_osobu(text):
    """
    Vrátí (jmeno, prijmeni) známé osoby z OCR textu, nebo (None, None).

    Jistota se posuzuje TVRDĚ: jméno i příjmení musí každé ZVLÁŠŤ sednout dost
    vysoko (ne jen jejich součet – ten dřív propustil dvě náhodně podobná slova
    a přiřkl cizí zdravotní kartu známé osobě), a vítěz musí mít jasný náskok
    před druhým kandidátem. Reálné čtení známého jména dává u obou polí
    ~0.85–1.0; po odfiltrování dokladových slov spadnou falešné shody hluboko
    pod práh 0.72.
    """
    if not text:
        return None, None
    nej = None            # (idx, skore_jmeno, skore_prijmeni)
    druhe_soucet = 0.0
    for i, osoba in enumerate(ZNAMI_LIDE):
        sj = _nejlepsi_shoda_v_textu(text, osoba["jmeno"])
        sp = _nejlepsi_shoda_v_textu(text, osoba["prijmeni"])
        soucet = sj + sp
        if nej is None or soucet > nej[1] + nej[2]:
            if nej is not None:
                druhe_soucet = nej[1] + nej[2]
            nej = (i, sj, sp)
        elif soucet > druhe_soucet:
            druhe_soucet = soucet
    if nej is None:
        return None, None
    idx, sj, sp = nej
    if sj >= 0.72 and sp >= 0.72 and (sj + sp) - druhe_soucet >= 0.2:
        osoba = ZNAMI_LIDE[idx]
        return osoba["jmeno"], osoba["prijmeni"]
    return None, None

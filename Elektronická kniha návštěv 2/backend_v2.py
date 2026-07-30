#!/usr/bin/env python3
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3, base64, io, re, os, secrets
from datetime import datetime
from PIL import Image
import pytesseract

app = Flask(__name__)
CORS(app)

DB_PATH = "navstevni_kniha.db"

# ── Přihlášení (admin / správce) ──────────────────────────────────────────
# Řadoví zaměstnanci se do tohohle rozhraní vůbec nepřihlašují — ti se jen
# naskenují u vchodu přes /sken (bez účtu). Recepční dashboard je jen pro
# admina a správce, oba mají plný přístup ke všem záznamům a hledání.
# Prototyp — PINy jde přepsat proměnnými prostředí ADMIN_PIN / SPRAVCE_PIN.
# Tokeny žijí jen v paměti procesu, po restartu serveru je nutné se přihlásit znovu.
ADMIN_PIN   = os.environ.get("ADMIN_PIN", "ept-admin-2026")
SPRAVCE_PIN = os.environ.get("SPRAVCE_PIN", "ept-spravce-2026")
TOKENS = {}  # token -> "admin" | "spravce"

def aktualni_role():
    return TOKENS.get(request.headers.get("X-Auth-Token"))

# ── Databáze ──────────────────────────────────────────────────────────────────
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS navstevnici (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                jmeno       TEXT NOT NULL,
                prijmeni    TEXT NOT NULL,
                organizace  TEXT DEFAULT '',
                spz         TEXT DEFAULT '',
                prichod_dt  TEXT NOT NULL,
                odchod_dt   TEXT
            )
        """)
        conn.commit()
 
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.route("/api/login", methods=["POST"])
def api_login():
    d = request.json or {}
    role = d.get("role")
    pin  = (d.get("pin") or "").strip()

    if role == "admin" and pin == ADMIN_PIN:
        pass
    elif role == "spravce" and pin == SPRAVCE_PIN:
        pass
    else:
        return jsonify({"error": "Nesprávné heslo."}), 401

    token = secrets.token_hex(16)
    TOKENS[token] = role
    return jsonify({"token": token, "role": role})

@app.route("/api/logout", methods=["POST"])
def api_logout():
    TOKENS.pop(request.headers.get("X-Auth-Token"), None)
    return jsonify({"status": "ok"})

# ── Hlavní stránka ────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('.', 'recepce.html')
 
@app.route('/sken')
def sken():
    return send_from_directory('.', 'sken.html')
 
# ── OCR ───────────────────────────────────────────────────────────────────────
@app.route("/api/ocr", methods=["POST"])
def api_ocr():
    try:
        data = request.json
        if not data or "image" not in data:
            return jsonify({"error": "Chybí pole 'image'"}), 400
 
        raw = data["image"]
        # Funguje s hlavičkou i bez ní
        img_b64 = raw.split(",", 1)[-1] if "," in raw else raw
 
        try:
            image_bytes = base64.b64decode(img_b64)
        except Exception:
            return jsonify({"error": "Neplatný base64 obrázek"}), 400
 
        image = Image.open(io.BytesIO(image_bytes))
 
        # Převod do RGB pokud je RGBA nebo jiný formát
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
 
        # OCR — čeština, fallback angličtina
        try:
            text = pytesseract.image_to_string(image, lang='ces')
        except Exception:
            text = pytesseract.image_to_string(image)
 
        jmeno, prijmeni = extrahuj_jmeno(text)
 
        return jsonify({
            "text":     text,
            "jmeno":    jmeno,
            "prijmeni": prijmeni
        })
 
    except Exception as e:
        return jsonify({"error": str(e)}), 500
 
 
def extrahuj_jmeno(text):
    """
    Extrahuje jméno a příjmení z OCR textu české občanky.
    Tesseract občas vrátí vše na jednom řádku a klíčová slova zkomolí,
    proto používáme fuzzy regex pro Příjmení/Surname a Jméno/Given names.
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
 
    if jmeno_val and prijmeni_val:
        return jmeno_val, prijmeni_val
 
    # Strategie 2: dva kapitalizovaná slova na řádku (přeskočit řádky s čísly)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    vzor  = re.compile(r'[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]{1,}')
    for line in lines:
        if re.search(r'\d{5,}', line): continue
        slova = vzor.findall(line)
        if len(slova) >= 2:
            return slova[0], slova[1]
 
    # Strategie 3: fallback — první dvě kapitalizovaná slova v celém textu
    vsechna = []
    for line in lines:
        if re.search(r'\d{5,}', line): continue
        vsechna.extend(vzor.findall(line))
    if len(vsechna) >= 2:
        return vsechna[0], vsechna[1]
 
    return "", ""
 
# ── Statistiky ────────────────────────────────────────────────────────────────
@app.route("/api/stats", methods=["GET"])
def api_stats():
    if not aktualni_role():
        return jsonify({"error": "Přihlaste se prosím."}), 401

    dnes = datetime.now().strftime("%Y-%m-%d")
    with get_db() as conn:
        aktivni = conn.execute(
            "SELECT COUNT(*) FROM navstevnici WHERE odchod_dt IS NULL"
        ).fetchone()[0]
        dnes_cnt = conn.execute(
            "SELECT COUNT(*) FROM navstevnici WHERE prichod_dt LIKE ?",
            (dnes + "%",)
        ).fetchone()[0]
        celkem = conn.execute(
            "SELECT COUNT(*) FROM navstevnici"
        ).fetchone()[0]
    return jsonify({"aktivni": aktivni, "dnes": dnes_cnt, "celkem": celkem})
 
# ── Návštěvníci GET + POST ────────────────────────────────────────────────────
@app.route("/api/navstevnici", methods=["GET", "POST"])
def api_navstevnici():
    role = aktualni_role()

    if request.method == "POST":
        if role not in ("admin", "spravce"):
            return jsonify({"error": "Přihlaste se prosím."}), 401

        d = request.json or {}
        jmeno    = (d.get("jmeno")    or "").strip()
        prijmeni = (d.get("prijmeni") or "").strip()

        if not jmeno or not prijmeni:
            return jsonify({"error": "Jméno a příjmení jsou povinné."}), 400

        prichod = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with get_db() as conn:
            cur = conn.execute(
                "INSERT INTO navstevnici (jmeno, prijmeni, organizace, spz, prichod_dt) VALUES (?,?,?,?,?)",
                (jmeno, prijmeni, d.get("organizace", ""), d.get("spz", ""), prichod)
            )
            new_id = cur.lastrowid
            conn.commit()

        return jsonify({"status": "ok", "id": new_id, "prichod_dt": prichod})

    # GET — filtrování + hledání (admin i správce vidí úplně vše)
    if role not in ("admin", "spravce"):
        return jsonify({"error": "Přihlaste se prosím."}), 401

    filtr     = request.args.get("filter", "aktivni")
    q         = (request.args.get("q") or "").strip()
    datum     = (request.args.get("datum") or "").strip()
    hodina_od = (request.args.get("hodina_od") or "").strip()
    hodina_do = (request.args.get("hodina_do") or "").strip()

    dnes = datetime.now().strftime("%Y-%m-%d")
    where  = []
    params = []

    if filtr == "aktivni":
        where.append("odchod_dt IS NULL")
    elif filtr == "dnes":
        where.append("prichod_dt LIKE ?")
        params.append(dnes + "%")
    elif filtr == "historie":
        where.append("odchod_dt IS NOT NULL")
    # filtr 'vse' / 'hledat' — bez základního omezení, jen filtry níže

    if q:
        where.append("(jmeno LIKE ? OR prijmeni LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    if datum:
        where.append("prichod_dt LIKE ?")
        params.append(datum + "%")
    if hodina_od:
        where.append("substr(prichod_dt, 12, 5) >= ?")
        params.append(hodina_od)
    if hodina_do:
        where.append("substr(prichod_dt, 12, 5) <= ?")
        params.append(hodina_do)

    sql = "SELECT * FROM navstevnici"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC"

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    return jsonify([dict(r) for r in rows])

# ── Úprava záznamu PATCH ──────────────────────────────────────────────────────
@app.route("/api/navstevnici/<int:nav_id>", methods=["PATCH"])
def api_navstevnik_patch(nav_id):
    if aktualni_role() not in ("admin", "spravce"):
        return jsonify({"error": "Přihlaste se prosím."}), 401

    d = request.json or {}

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM navstevnici WHERE id=?", (nav_id,)
        ).fetchone()
 
        if not row:
            return jsonify({"error": "Záznam nenalezen."}), 404
 
        if d.get("odchod"):
            if row["odchod_dt"]:
                return jsonify({"error": "Odchod již byl zapsán."}), 400
            odchod = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE navstevnici SET odchod_dt=? WHERE id=?",
                (odchod, nav_id)
            )
        else:
            org = d.get("organizace", row["organizace"] or "")
            spz = d.get("spz",        row["spz"]        or "")
            conn.execute(
                "UPDATE navstevnici SET organizace=?, spz=? WHERE id=?",
                (org, spz, nav_id)
            )
 
        conn.commit()
 
    return jsonify({"status": "ok"})
 
# ── Start ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    print("=" * 45)
    print("  Návštěvní kniha – backend")
    print("  http://localhost:5050")
    print("=" * 45)
    app.run(port=5050, host="0.0.0.0", debug=False)
 
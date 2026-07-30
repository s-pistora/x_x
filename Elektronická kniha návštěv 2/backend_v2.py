#!/usr/bin/env python3
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import base64, io, os, secrets
from datetime import datetime
from PIL import Image

import db_manager as db
import ocr_processor as ocr
from sms_notifier import validace_telefonu, send_sms_notification

app = Flask(__name__)
CORS(app)

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
# Bez přihlášení – používá to i samoobslužný sken-kiosek (/sken). Obrázek se
# nikde neukládá, jen se z něj vytáhne text.
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

        # OCR: EasyOCR (lokální síť) cílí přímo na pole PŘÍJMENÍ/JMÉNO podle
        # rozvržení občanky; fallback Tesseract.
        jmeno, prijmeni, text, engine = ocr.precti_doklad(image)

        if not jmeno and not prijmeni:
            with db.get_db() as conn:
                db.zapis_audit(conn, None, "ocr_selhani", f"OCR ({engine}) nerozpoznalo jméno ani příjmení")
                conn.commit()

        return jsonify({
            "text":     text,
            "jmeno":    jmeno,
            "prijmeni": prijmeni,
            "engine":   engine,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Statistiky ────────────────────────────────────────────────────────────────
@app.route("/api/stats", methods=["GET"])
def api_stats():
    if not aktualni_role():
        return jsonify({"error": "Přihlaste se prosím."}), 401

    dnes = datetime.now().strftime("%Y-%m-%d")
    with db.get_db() as conn:
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
    if request.method == "POST":
        # Zápis příchodu je otevřený – dělá ho recepční i samoobslužný sken-kiosek.
        # (Chceš-li i zápis za login, přidej sem kontrolu aktualni_role() jako u GET.)
        d = request.json or {}
        jmeno    = (d.get("jmeno")    or "").strip()
        prijmeni = (d.get("prijmeni") or "").strip()

        if not jmeno or not prijmeni:
            return jsonify({"error": "Jméno a příjmení jsou povinné."}), 400

        phone_number = ""
        telefon_raw = (d.get("phone_number") or "").strip()
        if telefon_raw:
            phone_number = validace_telefonu(telefon_raw)
            if not phone_number:
                return jsonify({"error": "Neplatný formát telefonu. Použijte +420xxxxxxxxx nebo 9 číslic."}), 400

        vysledek = db.zapis_prichod(jmeno, prijmeni, d.get("organizace", ""), d.get("spz", ""), phone_number)

        # Osoba je právě teď aktivní (ještě neodešla) – nezakládáme duplicitní řádek.
        if vysledek["status"] == "jiz_prihlasen":
            return jsonify({
                "status":     "jiz_prihlasen",
                "id":         vysledek["id"],
                "prichod_dt": vysledek["prichod_dt"],
                "error":      f"{jmeno} {prijmeni} je již přítomen/a od {vysledek['prichod_dt'][11:16]}.",
            }), 409

        if phone_number:
            cas = datetime.now().strftime("%H:%M:%S")
            zprava = f"Ahoj {jmeno} {prijmeni}, byl jsi úspěšně přihlášen/a do systému dne {cas}."
            send_sms_notification(phone_number, zprava)

        odpoved = {
            "status":       "ok",
            "id":           vysledek["id"],
            "prichod_dt":   vysledek["prichod_dt"],
            "vitejte_zpet": vysledek["vitejte_zpet"],
        }
        if vysledek["vitejte_zpet"]:
            posledni_dt = datetime.strptime(vysledek["posledni_navsteva"], "%Y-%m-%d %H:%M:%S")
            odpoved["zprava"] = (
                f"Vítejte zpět, {jmeno} {prijmeni}! "
                f"Poslední přihlášení: {posledni_dt.strftime('%d.%m.%Y v %H:%M')}."
            )

        return jsonify(odpoved)

    # GET — filtrování + hledání (admin i správce vidí úplně vše)
    role = aktualni_role()
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

    with db.get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    return jsonify([dict(r) for r in rows])

# ── Úprava záznamu PATCH ──────────────────────────────────────────────────────
@app.route("/api/navstevnici/<int:nav_id>", methods=["PATCH"])
def api_navstevnik_patch(nav_id):
    if aktualni_role() not in ("admin", "spravce"):
        return jsonify({"error": "Přihlaste se prosím."}), 401

    d = request.json or {}

    with db.get_db() as conn:
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
            db.zapis_audit(conn, nav_id, "odchod_zapsan", "")
            conn.commit()
            return jsonify({"status": "ok"})

        org = d.get("organizace", row["organizace"] or "")
        spz = d.get("spz",        row["spz"]        or "")
        conn.execute(
            "UPDATE navstevnici SET organizace=?, spz=? WHERE id=?",
            (org, spz, nav_id)
        )
        conn.commit()

    if "phone_number" in d:
        telefon_raw = (d.get("phone_number") or "").strip()
        phone_number = ""
        if telefon_raw:
            phone_number = validace_telefonu(telefon_raw)
            if not phone_number:
                return jsonify({"error": "Neplatný formát telefonu. Použijte +420xxxxxxxxx nebo 9 číslic."}), 400
        _, zmenil_se = db.aktualizuj_telefon(nav_id, phone_number)
        if zmenil_se and phone_number:
            send_sms_notification(
                phone_number,
                "Vaše telefonní číslo bylo úspěšně aktualizováno v evidenci návštěv."
            )

    return jsonify({"status": "ok"})

# ── Start ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    db.init_db()
    print("=" * 45)
    print("  Návštěvní kniha – backend")
    print("  http://localhost:5050")
    print("=" * 45)
    app.run(port=5050, host="0.0.0.0", debug=False)

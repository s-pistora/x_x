#!/usr/bin/env python3
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
import base64, csv, io, os, secrets, socket
from datetime import datetime
from PIL import Image

# .env načítáme explicitně a jako první. Dřív se to dělo jen jako vedlejší efekt
# importu sms_notifier — fungovalo to díky pořadí importů, ale stačilo je přehodit
# a PINy z .env by se přestaly načítat, aniž by to cokoliv nahlásilo.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv je nepovinné – bez něj se čte jen z prostředí

import db_manager as db
import ocr_processor as ocr
from sms_notifier import validace_telefonu, send_sms_notification

app = Flask(__name__)
CORS(app)

# Schéma zakládáme při IMPORTU, ne v __main__. Pod WSGI (waitress) se __main__
# nespustí, takže by aplikace běžela nad databází bez tabulek a každý endpoint
# by vracel 500. Není to teorie — přesně tohle se stalo, když git smazal DB
# souboru a sqlite3.connect() ho vyrobil prázdný.
db.init_db()

# OCR model se načítá LÍNĚ, až při prvním skenu. Načítat ho dopředu v tomhle
# procesu nelze: torch si inicializuje vlastní vlákna a ve spojení s vláknovým
# serverem to zablokovalo i TLS handshake — server poslouchal, ale neodpověděl
# vůbec, bez chyby a bez záznamu v logu. Zkoušeno na pozadí i synchronně, obojí
# stejně. Cena líného načtení je ~3 s u prvního snímku (model je na disku
# v cache); sken jich posílá víc, takže se to schová do průběhu skenování.
# Rozpoznávání jde přes zámek v ocr_processor, aby nikdy neběželo dvakrát zaráz.

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

# ── Adresa v místní síti ──────────────────────────────────────────────────────
# Používá se pro výpis adres při startu serveru: sken se otevírá na telefonu,
# takže potřebujeme síťovou IP, ne localhost — ten by telefon poslal na sebe sama.

def lan_adresa():
    """IP tohohle stroje v místní síti. Necháme OS vybrat rozhraní, kterým by
    ven odcházel provoz — spolehlivější než hádat en0/en1. Spojení se reálně
    neotevírá, jde jen o zjištění zdrojové adresy."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def zakladni_url():
    """Adresa, na kterou se chodí zvenčí — tu vypisujeme při startu.

    Za TLS proxy to není adresa aplikace: aplikace poslouchá na 5051 na
    localhostu, ale navenek se chodí na 5050 přes https. Proto se veřejný port
    a schéma berou zvlášť (EPT_PUBLIC_PORT / EPT_HTTPS), ne z PORT.
    """
    port = os.environ.get("EPT_PUBLIC_PORT") or os.environ.get("PORT", "5050")
    schema = "https" if os.environ.get("EPT_HTTPS") == "1" else "http"
    return f"{schema}://{lan_adresa()}:{port}"


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

        # DOČASNÝ DEBUG (EPT_OCR_DEBUG=1): uloží snímek + přečtený text, ať se dá
        # extrakce jména odladit offline. Odstranit po vyřešení.
        if os.environ.get("EPT_OCR_DEBUG") == "1":
            try:
                import time as _t
                _dir = os.path.join(os.path.dirname(__file__), "debug_ocr")
                os.makedirs(_dir, exist_ok=True)
                _stamp = _t.strftime("%H%M%S")
                image.save(os.path.join(_dir, f"sken_{_stamp}.png"))
                with open(os.path.join(_dir, "posledni_text.txt"), "w", encoding="utf-8") as _f:
                    _f.write(f"engine={engine} jmeno={jmeno!r} prijmeni={prijmeni!r}\n---TEXT---\n{text}\n")
                print(f"[OCR DEBUG] sken_{_stamp}.png | jmeno={jmeno!r} prijmeni={prijmeni!r}", flush=True)
            except Exception as _e:
                print(f"[OCR DEBUG] selhalo: {_e}", flush=True)

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

# ── Audit log ─────────────────────────────────────────────────────────────────
# Akce se logovaly od začátku, ale nebylo je kde vidět. Pro dohledatelnost
# (a pro GDPR doložení „kdo, co, kdy") je potřeba na ně vidět z rozhraní.
AUDIT_POPISKY = {
    "novy_navstevnik":    "Nový návštěvník",
    "opakovana_navsteva": "Opakovaná návštěva",
    "jiz_prihlasen":      "Pokus o duplicitní příchod",
    "odchod_zapsan":      "Zapsán odchod",
    "telefon_zmenen":     "Změna telefonu",
    "ocr_selhani":        "OCR nerozpoznalo doklad",
}


@app.route("/api/audit", methods=["GET"])
def api_audit():
    if aktualni_role() not in ("admin", "spravce"):
        return jsonify({"error": "Přihlaste se prosím."}), 401

    limit = min(int(request.args.get("limit", 100)), 500)
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT a.*, n.jmeno, n.prijmeni FROM audit_log a "
            "LEFT JOIN navstevnici n ON n.id = a.navstevnik_id "
            "ORDER BY a.timestamp DESC, a.id DESC LIMIT ?", (limit,)
        ).fetchall()

    return jsonify([{
        "id":        r["id"],
        "cas":       r["timestamp"],
        "akce":      r["action"],
        "akce_text": AUDIT_POPISKY.get(r["action"], r["action"]),
        "osoba":     f'{r["jmeno"]} {r["prijmeni"]}' if r["jmeno"] else "—",
        "detail":    r["details"] or "",
    } for r in rows])


# ── Export do CSV ─────────────────────────────────────────────────────────────
@app.route("/api/export.csv", methods=["GET"])
def api_export_csv():
    if aktualni_role() not in ("admin", "spravce"):
        return jsonify({"error": "Přihlaste se prosím."}), 401

    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT jmeno, prijmeni, organizace, spz, phone_number, prichod_dt, odchod_dt "
            "FROM navstevnici ORDER BY prichod_dt DESC"
        ).fetchall()

    buf = io.StringIO()
    # Excel v české lokalizaci čeká středník, ne čárku
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    w.writerow(["Jméno", "Příjmení", "Organizace", "SPZ", "Telefon",
                "Příchod", "Odchod", "Doba (min)"])
    for r in rows:
        doba = ""
        if r["odchod_dt"]:
            d = (datetime.strptime(r["odchod_dt"], "%Y-%m-%d %H:%M:%S")
                 - datetime.strptime(r["prichod_dt"], "%Y-%m-%d %H:%M:%S"))
            doba = int(d.total_seconds() // 60)
        w.writerow([r["jmeno"], r["prijmeni"], r["organizace"] or "", r["spz"] or "",
                    r["phone_number"] or "", r["prichod_dt"], r["odchod_dt"] or "", doba])

    # BOM: bez něj Excel na Windows rozsype diakritiku (Nováková → NovÃ¡kovÃ¡)
    data = "﻿" + buf.getvalue()
    nazev = f"navstevy-{datetime.now().strftime('%Y-%m-%d')}.csv"
    return Response(data, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nazev}"'})


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
# init_db() se volá výš, při importu — pod WSGI se tenhle blok nespustí.
if __name__ == "__main__":
    # TLS tady záměrně NEřešíme. Werkzeug s ssl_context se ukázal jako
    # nespolehlivý (po restartu přestal odpovídat na handshake, na plain HTTP
    # jel dál), takže https ukončuje tls_proxy.py. Pro celé demo: ./start_demo.sh
    port = int(os.environ.get("PORT", "5050"))

    print("=" * 58)
    print("  Návštěvní kniha – aplikace")
    print(f"  poslouchá na portu {port} (HTTP)")
    print(f"  veřejná adresa:  {zakladni_url()}/")
    print(f"  sken:            {zakladni_url()}/sken")
    if os.environ.get("EPT_HTTPS") != "1":
        print()
        print("  Bez HTTPS kamera na telefonu nepojede.")
        print("  Celé demo naráz: ./start_demo.sh")
    print("=" * 58)

    app.run(port=port, host="0.0.0.0", debug=False)

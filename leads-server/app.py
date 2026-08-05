#!/usr/bin/env python3
"""Server pro poptávkový formulář na one-pageru (docs/index.html).

Samostatná služba mimo hlavní recepční appku ("Elektronická kniha návštěv 2") —
ta musí zůstat izolovaná od internetu, kdežto tohle musí být naopak veřejně
dostupné, protože formulář vyplňují cizí lidé z veřejné stránky. Ukládá
poptávky do databáze (pro /admin přehled) a zároveň posílá e-mailové
upozornění, stejným "zapnuto env proměnnou, jinak mock" vzorem jako
sms_notifier.py v hlavní appce.
"""
import os
import secrets
import smtplib
import sqlite3
from datetime import datetime
from email.mime.text import MIMEText

from flask import Flask, request, jsonify, g, send_from_directory
from flask_cors import CORS

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
CORS(app)

DB_PATH = os.environ.get("LEADS_DB_PATH", os.path.join(os.path.dirname(__file__), "leads.db"))

ADMIN_PIN = os.environ.get("ADMIN_PIN", "zmen-me-2026")
TOKENS = {}  # token -> True, stejný jednoduchý vzor jako TOKENS v backend_v2.py

EMAIL_ENABLED = os.environ.get("EMAIL_ENABLED", "false").lower() == "true"
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
NOTIFY_TO = os.environ.get("NOTIFY_TO", GMAIL_USER)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            email      TEXT NOT NULL,
            telefon    TEXT DEFAULT '',
            zprava     TEXT DEFAULT '',
            stav       TEXT DEFAULT 'nove',
            vytvoreno  TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


# Schéma zakládáme při IMPORTU, ne v __main__ — pod gunicornem se __main__
# nespustí (stejný důvod jako v backend_v2.py).
init_db()


def posli_email(lead):
    """Pošle upozornění na novou poptávku. Bez EMAIL_ENABLED jen vypíše do
    logu (mock) — server tak jde vyzkoušet i bez nastaveného Gmailu."""
    if not EMAIL_ENABLED:
        print(f"[EMAIL MOCK] Nová poptávka: {lead['email']} / {lead['telefon']}")
        return
    if not (GMAIL_USER and GMAIL_APP_PASSWORD and NOTIFY_TO):
        print("[EMAIL] EMAIL_ENABLED=true, ale chybí GMAIL_USER/GMAIL_APP_PASSWORD/NOTIFY_TO — přeskakuji.")
        return
    try:
        text = (
            f"Nová poptávka z one-pageru\n\n"
            f"E-mail: {lead['email']}\n"
            f"Telefon: {lead['telefon'] or '—'}\n"
            f"Co by chtěli pozměnit:\n{lead['zprava']}\n"
        )
        msg = MIMEText(text, _charset="utf-8")
        msg["Subject"] = "Nová poptávka — Digitální recepce"
        msg["From"] = GMAIL_USER
        msg["To"] = NOTIFY_TO
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, [NOTIFY_TO], msg.as_string())
    except Exception as e:
        # E-mail je jen upozornění navíc — poptávka je bezpečně uložená v DB
        # i když odeslání e-mailu selže, proto se tu nic dál nehází.
        print(f"[EMAIL] Odeslání selhalo: {e}")


@app.route("/")
def index():
    return jsonify({"status": "ok", "service": "leads-server"})


@app.route("/admin")
def admin_page():
    return send_from_directory(os.path.dirname(__file__), "admin.html")


@app.route("/api/lead", methods=["POST"])
def api_lead():
    d = request.json or {}
    email = (d.get("email") or "").strip()
    telefon = (d.get("telefon") or "").strip()
    zprava = (d.get("zprava") or "").strip()

    if not email or not zprava:
        return jsonify({"error": "E-mail a zpráva jsou povinné."}), 400

    vytvoreno = datetime.now().isoformat(timespec="seconds")
    db = get_db()
    db.execute(
        "INSERT INTO leads (email, telefon, zprava, stav, vytvoreno) VALUES (?, ?, ?, 'nove', ?)",
        (email, telefon, zprava, vytvoreno),
    )
    db.commit()

    posli_email({"email": email, "telefon": telefon, "zprava": zprava})
    return jsonify({"status": "ok"})


# ── Admin ────────────────────────────────────────────────────────────────────
def aktualni_token_platny():
    return TOKENS.get(request.headers.get("X-Auth-Token")) is True


@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    d = request.json or {}
    pin = (d.get("pin") or "").strip()
    if pin != ADMIN_PIN:
        return jsonify({"error": "Nesprávný PIN."}), 401
    token = secrets.token_hex(16)
    TOKENS[token] = True
    return jsonify({"token": token})


@app.route("/api/admin/logout", methods=["POST"])
def api_admin_logout():
    TOKENS.pop(request.headers.get("X-Auth-Token"), None)
    return jsonify({"status": "ok"})


@app.route("/api/admin/leads", methods=["GET"])
def api_admin_leads():
    if not aktualni_token_platny():
        return jsonify({"error": "Nepřihlášeno."}), 401

    q = (request.args.get("q") or "").strip().lower()
    stav = (request.args.get("stav") or "").strip()

    db = get_db()
    rows = db.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
    vysledek = []
    for r in rows:
        if stav and r["stav"] != stav:
            continue
        if q and q not in (r["email"] + r["telefon"] + r["zprava"]).lower():
            continue
        vysledek.append(dict(r))
    return jsonify(vysledek)


@app.route("/api/admin/leads/<int:lead_id>", methods=["PATCH"])
def api_admin_lead_update(lead_id):
    if not aktualni_token_platny():
        return jsonify({"error": "Nepřihlášeno."}), 401
    d = request.json or {}
    stav = d.get("stav")
    if stav not in ("nove", "kontaktovano", "vyrizeno"):
        return jsonify({"error": "Neplatný stav."}), 400
    db = get_db()
    db.execute("UPDATE leads SET stav = ? WHERE id = ?", (stav, lead_id))
    db.commit()
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5100)), debug=False)

#!/usr/bin/env python3
"""Validace telefonních čísel a odesílání SMS notifikací (mock / Twilio)."""
import os
import re
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv je nepovinné – bez něj se čte jen z prostředí (env)

SMS_ENABLED = os.environ.get("SMS_ENABLED", "false").strip().lower() == "true"
COOLDOWN_SECONDS = int(os.environ.get("SMS_COOLDOWN_SECONDS", "10"))

TWILIO_ACCOUNT_SID  = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN   = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER  = os.environ.get("TWILIO_FROM_NUMBER", "")

_TELEFON_RE = re.compile(r"^(?:\+420)?(\d{9})$")

# Poslední odeslání SMS podle čísla – jednoduchý rate limiting (viz lze_odeslat).
# Žije jen v paměti procesu, což stačí pro jeden dev/recepční server;
# při více workerech/procesech by to muselo jít přes DB nebo sdílenou cache.
_posledni_odeslani = {}


def validace_telefonu(cislo):
    """Přijme '+420xxxxxxxxx' nebo 9 číslic. Vrátí normalizovaný tvar '+420xxxxxxxxx', nebo None."""
    if not cislo:
        return None
    cislo = cislo.strip().replace(" ", "")
    m = _TELEFON_RE.match(cislo)
    if not m:
        return None
    return "+420" + m.group(1)


def lze_odeslat(phone_number):
    """Rate limiting – mezi dvěma SMS na stejné číslo musí uplynout aspoň COOLDOWN_SECONDS."""
    posledni = _posledni_odeslani.get(phone_number)
    return posledni is None or (time.time() - posledni) >= COOLDOWN_SECONDS


def send_sms_notification(phone_number, message):
    """
    Odešle SMS notifikaci. Respektuje cooldown (viz lze_odeslat) – pokud je aktivní,
    SMS se přeskočí (vrátí se status 'cooldown'), aby nešlo systém zneužít ke spamu.

    Bez nastaveného SMS_ENABLED=true v .env se SMS jen vypíše do konzole/logu –
    to je bezpečný výchozí stav pro vývoj a testování bez Twilio účtu.
    """
    if not phone_number:
        return {"status": "bez_cisla"}

    if not lze_odeslat(phone_number):
        return {"status": "cooldown"}

    _posledni_odeslani[phone_number] = time.time()

    if not SMS_ENABLED:
        print(f"[SMS MOCK] -> {phone_number}: {message}")
        return {"status": "mock_odeslano"}

    # ── OSTRÁ TWILIO INTEGRACE ────────────────────────────────────────────────
    # Odblokuje se automaticky nastavením SMS_ENABLED=true v .env (viz .env.example)
    # a instalací knihovny: pip install twilio
    from twilio.rest import Client  # noqa: importováno až tady, aby twilio nebylo povinné

    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    client.messages.create(body=message, from_=TWILIO_FROM_NUMBER, to=phone_number)
    return {"status": "odeslano"}

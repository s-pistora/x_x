#!/usr/bin/env python3
"""Odesílání e-mailu hostiteli, když se u kiosku odbaví jeho návštěva.

Mock (výchozí) / Resend (transakční API, ale bez vlastní ověřené domény smí
jen na vlastníka Resend účtu) / Gmail SMTP (žádný takový limit, ale
vyžaduje Gmail App Password). Přepíná se přes EMAIL_PROVIDER v .env.
"""
import json
import os
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv je nepovinné – bez něj se čte jen z prostředí (env)

EMAIL_ENABLED = os.environ.get("EMAIL_ENABLED", "false").strip().lower() == "true"
EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "resend").strip().lower()

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
RESEND_URL = "https://api.resend.com/emails"

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")


def send_arrival_email(email, navstevnik_jmeno, navstevnik_prijmeni, host_jmeno, cas):
    """
    Pošle hostiteli e-mail, že mu dorazila návštěva. Bez nastaveného
    EMAIL_ENABLED=true v .env se e-mail jen vypíše do konzole/logu – bezpečný
    výchozí stav pro vývoj a testování bez účtu u kterékoli služby.
    """
    if not email:
        return {"status": "bez_emailu"}

    predmet = f"Návštěva u vstupu: {navstevnik_jmeno} {navstevnik_prijmeni}"
    telo = (
        f"Dobrý den {host_jmeno},\n\n"
        f"u vstupu se právě odbavil(a) {navstevnik_jmeno} {navstevnik_prijmeni} "
        f"({cas}) a čeká na vás.\n"
    )

    if not EMAIL_ENABLED:
        print(f"[EMAIL MOCK] -> {email}: {predmet}\n{telo}")
        return {"status": "mock_odeslano"}

    if EMAIL_PROVIDER == "gmail":
        return _posli_pres_gmail(email, predmet, telo)
    return _posli_pres_resend(email, predmet, telo)


def _posli_pres_resend(email, predmet, telo):
    # POZOR: bez vlastní ověřené domény v Resendu (RESEND_FROM_EMAIL zůstane
    # na sandboxové onboarding@resend.dev) Resend povolí posílat jen na
    # e-mail vlastníka Resend účtu, ne na libovolnou adresu – reálně ověřeno,
    # ne teorie. Na to, aby appka posílala komukoliv, je potřeba buď ověřit
    # doménu na resend.com/domains, nebo přepnout EMAIL_PROVIDER=gmail.
    data = json.dumps({
        "from": RESEND_FROM_EMAIL,
        "to": [email],
        "subject": predmet,
        "text": telo,
    }).encode("utf-8")

    req = urllib.request.Request(
        RESEND_URL,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
            # Bez User-Agent posílá urllib "Python-urllib/x.x", což Cloudflare
            # před Resend API blokuje jako podezřelé (403 "error code: 1010") –
            # ne skutečná chyba Resendu, jen chybějící běžná hlavička.
            "User-Agent": "navstevni-kniha-ept/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            json.loads(resp.read().decode("utf-8"))
            return {"status": "odeslano"}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        print(f"[EMAIL] Resend selhal ({e.code}): {detail}")
        return {"status": "chyba", "detail": detail}


def _posli_pres_gmail(email, predmet, telo):
    # GMAIL_APP_PASSWORD musí být App Password z
    # myaccount.google.com/apppasswords (vyžaduje zapnuté dvoufázové ověření
    # na tom Google účtu), NE běžné heslo do účtu – to Google pro SMTP
    # přihlášení odmítne. Narozdíl od Resendu tu není žádný limit na
    # příjemce, jde poslat komukoliv.
    zprava = EmailMessage()
    zprava["Subject"] = predmet
    zprava["From"] = GMAIL_ADDRESS
    zprava["To"] = email
    zprava.set_content(telo)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            smtp.send_message(zprava)
        return {"status": "odeslano"}
    except smtplib.SMTPException as e:
        print(f"[EMAIL] Gmail SMTP selhal: {e}")
        return {"status": "chyba", "detail": str(e)}

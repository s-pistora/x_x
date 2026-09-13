#!/bin/sh
# Jednorázový setup prostředí pro běh appky přímo v iSH na iPadu
# (https://apps.apple.com/app/ish-shell/id1436902243 — appka se jmenuje
# "iSH Shell". Pozor: "iSH-AOK" NENÍ na App Store, to je jen fork zdrojáků
# na GitHubu k ručnímu sestavení přes Xcode — nepotřebujeme ho, iSH Shell
# používá stejný Alpine Linux + apk, takže má přístup ke stejným balíčkům).
#
# Spustit uvnitř iSH po prvním otevření appky (potřebuje síť pro apk/pip):
#   sh ish_ipad_setup.sh
#
# Záměrně bez easyocr: potřebuje PyTorch, který se v emulovaném x86 na iPadu
# nesestaví v rozumném čase. Appka na to má vestavěný fallback na tesseract
# (viz ocr_processor.py) — o nic se tu starat nemusíme, jen mu dát to, co
# potřebuje: balík tesseract-ocr + pytesseract.
set -e

# iSH defaultně ukazuje na svoje vlastní (omezené) repo, ne na plný Alpine.
# py3-opencv je jen v "community" větvi, kterou je potřeba zapnout ručně –
# https://github.com/ish-app/ish/wiki/Using-Alpine-Linux-repositories
# (v3.19 je verze, na které iSH aktuálně běží).
echo "https://dl-cdn.alpinelinux.org/alpine/v3.19/main" > /etc/apk/repositories
echo "https://dl-cdn.alpinelinux.org/alpine/v3.19/community" >> /etc/apk/repositories

apk update

# Kritické balíčky – bez nich appka vůbec neběží. Necháme spadnout celý
# skript, když tohle selže (set -e), protože bez nich nemá cenu pokračovat.
apk add python3 py3-pip tesseract-ocr tesseract-ocr-data-ces openssl git bash curl

# py3-sqlite3 SCHVÁLNĚ NENÍ v seznamu výš – takový balíček v Alpine vůbec
# neexistuje, sqlite3 modul je součástí základního balíku python3.

# Nekritické balíčky (numpy/opencv/pillow) – vylepšují kvalitu OCR (ořez
# karty, binarizace), ale appka bez nich pořád funguje (ocr_processor.py má
# na chybějící cv2 wrapované try/except všude, kde se používá). Instalujeme
# každý zvlášť, ať jeden chybějící/přejmenovaný balíček nesrazí zbytek –
# apk add se sadou balíčků najednou je transakce, jedno "no such package"
# by zrušilo úplně všechno v tom příkazu (přesně tohle nás dřív připravilo
# i o bash).
for balicek in py3-numpy py3-opencv py3-pillow; do
  apk add "$balicek" || echo "! $balicek se nepodařilo nainstalovat, appka pojede bez něj (nižší kvalita OCR na vzdálených fotkách)"
done

pip install --no-cache-dir flask flask-cors python-dotenv pytesseract

echo
echo "Hotovo. Dál:"
echo "  sh start_all_ipad.sh"

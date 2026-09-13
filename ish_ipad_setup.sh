#!/bin/sh
# Jednorázový setup prostředí pro běh appky přímo v iSH-AOK na iPadu
# (https://apps.apple.com/app/ish-shell/id1436902243 — instalovat fork
# "iSH-AOK" z App Store, ne původní iSH, ten má oříznuté balíčky).
#
# Spustit uvnitř iSH po prvním otevření appky (potřebuje síť pro apk/pip):
#   sh ish_ipad_setup.sh
#
# Záměrně bez easyocr: potřebuje PyTorch, který se v emulovaném x86 na iPadu
# nesestaví v rozumném čase. Appka na to má vestavěný fallback na tesseract
# (viz ocr_processor.py) — o nic se tu starat nemusíme, jen mu dát to, co
# potřebuje: balík tesseract-ocr + pytesseract.
set -e

apk update
apk add \
  python3 py3-pip py3-sqlite3 py3-numpy py3-opencv py3-pillow \
  tesseract-ocr tesseract-ocr-data-ces \
  openssl git bash curl

pip install --no-cache-dir flask flask-cors python-dotenv pytesseract

echo
echo "Hotovo. Dál:"
echo "  sh start_all_ipad.sh"

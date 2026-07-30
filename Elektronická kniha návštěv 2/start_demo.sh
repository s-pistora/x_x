#!/bin/bash
# Spustí celé demo jedním příkazem: aplikaci na HTTP + TLS proxy před ní.
#
# Rozdělení je kvůli kameře na telefonu — ta funguje jen na https, a Flaskův
# vývojový server se v TLS ukázal jako nespolehlivý (po restartu přestal
# odpovídat na handshake). Aplikace tedy jede čistě, TLS ukončuje tls_proxy.py.
#
#   recepce (notebook):  https://localhost:5050/
#   sken (telefon):      https://<lan-ip>:5050/sken
#
# Ukončení: Ctrl+C ukončí obojí.
set -euo pipefail
cd "$(dirname "$0")"

export PORT=5051                 # aplikace, jen na localhostu
export EPT_PUBLIC_PORT=5050      # port, na který chodí telefon
export EPT_HTTPS=1               # aby QR nabízel https adresu

if [ ! -f cert/server.crt ]; then
  echo "Certifikát chybí, generuji…"
  ./nastav_https.sh
fi

# Certifikát je vázaný na IP. Po přechodu do jiné sítě (zasedačka) je potřeba
# ho vygenerovat znovu, jinak ho telefon odmítne.
CERT_IP=$(openssl x509 -in cert/server.crt -noout -text \
  | grep -A1 "Subject Alternative Name" | tail -1 | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' | head -1)
LAN_IP=$(python3 -c "
import socket
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
try: s.connect(('8.8.8.8',80)); print(s.getsockname()[0])
except OSError: print('127.0.0.1')
finally: s.close()")

if [ "$CERT_IP" != "$LAN_IP" ]; then
  echo "IP se změnila ($CERT_IP → $LAN_IP), generuji certifikát znovu…"
  ./nastav_https.sh >/dev/null
fi

uklid() { kill "${APP_PID:-0}" "${PROXY_PID:-0}" 2>/dev/null || true; }
trap uklid EXIT INT TERM

python3 backend_v2.py > ../backend.log 2>&1 &
APP_PID=$!

# Počkat, až aplikace opravdu odpovídá — proxy by jinak první požadavky odmítla.
for _ in $(seq 1 40); do
  if curl -s -m 2 -o /dev/null "http://127.0.0.1:$PORT/"; then break; fi
  sleep 0.5
done

python3 tls_proxy.py > ../tls-proxy.log 2>&1 &
PROXY_PID=$!
sleep 1

echo "════════════════════════════════════════════════════════════"
echo "  Digitální kniha návštěv — demo běží"
echo
echo "  Recepce (tento počítač):  https://localhost:5050/"
echo "  Sken (telefon):           https://$LAN_IP:5050/sken"
echo
echo "  Telefon při prvním otevření potvrdí certifikát:"
echo "     Pokročilé → Pokračovat. Bez toho kamera nepojede."
echo
echo "  Logy: ../backend.log, ../tls-proxy.log"
echo "  Ukončení: Ctrl+C"
echo "════════════════════════════════════════════════════════════"

wait

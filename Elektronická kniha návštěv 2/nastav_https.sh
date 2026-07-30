#!/bin/bash
# Vygeneruje self-signed certifikát pro běh na místní síti.
#
# K čemu to je: prohlížeče pustí kameru (getUserMedia) jen na zabezpečeném
# původu — https, nebo localhost. Samoobslužný sken na telefonu tedy přes
# http://192.168.x.x nefunguje, kamera se ani nezeptá. S tímhle certifikátem
# ano; telefon jednou odklikne varování, že vydavatele nezná.
#
# Cert se váže na AKTUÁLNÍ IP, takže po přechodu do jiné sítě (zasedačka!)
# ho pusť znovu. Detekce IP je stejná jako v backendu (lan_adresa()).
set -euo pipefail
cd "$(dirname "$0")"

IP=$(python3 -c "
import socket
s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(('8.8.8.8',80)); print(s.getsockname()[0])
except OSError:
    print('127.0.0.1')
finally:
    s.close()")

mkdir -p cert

# subjectAltName je POVINNÝ. Moderní prohlížeče CN ignorují a bez SAN cert
# odmítnou úplně — nešel by ani odkliknout. IP i localhost, ať funguje obojí.
cat > cert/openssl.cnf <<EOF
[req]
distinguished_name = dn
x509_extensions    = v3
prompt             = no

[dn]
C  = CZ
O  = ept connectors
CN = Navstevni kniha ($IP)

[v3]
subjectAltName   = IP:$IP, IP:127.0.0.1, DNS:localhost
basicConstraints = critical, CA:FALSE
keyUsage         = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
EOF

openssl req -x509 -newkey rsa:2048 -sha256 -days 30 -nodes \
  -keyout cert/server.key -out cert/server.crt \
  -config cert/openssl.cnf >/dev/null 2>&1

chmod 600 cert/server.key

echo "certifikát vytvořen pro IP $IP (platnost 30 dnů)"
echo
echo "Spusť server takto:"
echo "  EPT_HTTPS=1 python3 backend_v2.py"
echo
echo "Na telefonu otevři:"
echo "  https://$IP:5050/sken"
echo "  → prohlížeč varuje, že certifikát nezná: Pokročilé → Pokračovat."
echo "     Bez tohohle kroku kamera nepojede."
echo
# macOS má LibreSSL, které nezná `-ext subjectAltName` → čteme přes -text.
# Kontrola je tu záměrně: bez SAN je cert pro prohlížeč nepoužitelný.
echo "Ověření SAN v certifikátu:"
openssl x509 -in cert/server.crt -noout -text \
  | grep -A1 "Subject Alternative Name" | tail -1 | sed 's/^ */  /'

#!/bin/sh
# Spustí všechny tři servery appky přímo na iPadu (v iSH-AOK), aby fungovaly
# bez jakéhokoli jiného počítače v síti.
#
#   iPad kiosek / recepce / sken:  https://localhost:5050/...  (přes TLS proxy,
#                                   kamera to jinak vůbec nepustí — stejný
#                                   princip jako u telefonu v start_demo.sh)
#   leads-server (poptávky+admin): http://localhost:5100/...
#   one-pager (docs, GitHub Pages): http://localhost:8000/
#
# Předpokládá proběhlý ./ish_ipad_setup.sh. Certifikát pro TLS proxy se
# vygeneruje sám při prvním spuštění (nastav_https.sh) — je vázaný na aktuální
# IP/localhost, po 30 dnech nebo změně sítě ho spusť znovu ručně.
#
# Ukončení: Ctrl+C (ukončí všechny čtyři procesy).
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$ROOT/Elektronická kniha návštěv 2"
LEADS_DIR="$ROOT/leads-server"
DOCS_DIR="$ROOT/docs"

uklid() {
  kill "${APP_PID:-0}" "${PROXY_PID:-0}" "${LEADS_PID:-0}" "${DOCS_PID:-0}" 2>/dev/null || true
}
trap uklid EXIT INT TERM

cd "$APP_DIR"
[ -f cert/server.crt ] || ./nastav_https.sh

PORT=5051 OCR_STRICT_WHITELIST=0 EPT_OCR_DEBUG=1 python3 backend_v2.py > /tmp/app.log 2>&1 &
APP_PID=$!
for _ in $(seq 1 40); do
  curl -s -m 2 -o /dev/null "http://127.0.0.1:5051/" && break
  sleep 0.5
done

EPT_PUBLIC_PORT=5050 PORT=5051 python3 tls_proxy.py > /tmp/tls-proxy.log 2>&1 &
PROXY_PID=$!

cd "$LEADS_DIR"
PORT=5100 python3 app.py > /tmp/leads.log 2>&1 &
LEADS_PID=$!

cd "$DOCS_DIR"
python3 -m http.server 8000 > /tmp/docs.log 2>&1 &
DOCS_PID=$!

cat <<'EOF'
════════════════════════════════════════════════════════
  Vše běží přímo na iPadu — v Safari na tomtéž iPadu otevři:

  iPad kiosek     https://localhost:5050/ipad
  Recepce         https://localhost:5050/
  Sken            https://localhost:5050/sken
  Leads landing   http://localhost:5100/
  Leads admin     http://localhost:5100/admin
  One-pager       http://localhost:8000/

  Při prvním otevření https adresy Safari ukáže "Tento web není
  zabezpečený" — je to náš vlastní certifikát, rozklikni Zobrazit
  podrobnosti → Přesto navštívit. Bez toho krok kamera nenaběhne.

  Drž iSH otevřené (ideálně ve Split View vedle Safari) — v
  pozadí ho iOS po chvíli uspí a server spadne.

  Logy: /tmp/app.log /tmp/tls-proxy.log /tmp/leads.log /tmp/docs.log
  Ukončení: Ctrl+C
════════════════════════════════════════════════════════
EOF

wait

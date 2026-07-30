#!/usr/bin/env python3
"""TLS proxy před aplikací — kvůli kameře na telefonu.

Proč vůbec: prohlížeče pustí `getUserMedia` jen na zabezpečeném původu, takže
samoobslužný sken na telefonu potřebuje https. Flask umí `ssl_context`, ale jeho
vývojový server se v tom na tomhle stroji ukázal jako nespolehlivý — jednou
obsloužil požadavky a po restartu už na TLS handshake nereagoval vůbec, přitom
na čistém HTTP odpovídal normálně. Na tom nechceme mít postavené živé demo.

Řešení: aplikace jede na plain HTTP na 127.0.0.1, TLS ukončuje tenhle skript.
Je to stejné rozvržení jako v produkci za nginxem nebo Caddy, jen bez závislostí
— všechno je ze standardní knihovny.

Spuštění (dvě okna, nebo ./start_demo.sh, který udělá obojí):
    python3 backend_v2.py                  # aplikace, port 5051
    python3 tls_proxy.py                   # TLS na portu 5050
"""
import os
import socket
import ssl
import sys
import threading

CERT = "cert/server.crt"
KEY = "cert/server.key"
POSLOUCHAT = ("0.0.0.0", int(os.environ.get("EPT_PUBLIC_PORT", "5050")))
APLIKACE = ("127.0.0.1", int(os.environ.get("PORT", "5051")))


def preleje(zdroj, cil):
    """Přelévá data jedním směrem, dokud spojení nedojde."""
    try:
        while True:
            data = zdroj.recv(65536)
            if not data:
                break
            cil.sendall(data)
    except OSError:
        pass
    finally:
        # Zavřít jen svůj směr — druhé vlákno může ještě dopisovat.
        try:
            cil.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def obsluz(klient):
    try:
        with socket.create_connection(APLIKACE, timeout=10) as app:
            a = threading.Thread(target=preleje, args=(klient, app), daemon=True)
            b = threading.Thread(target=preleje, args=(app, klient), daemon=True)
            a.start(); b.start()
            a.join(); b.join()
    except OSError as e:
        # Nejčastěji: aplikace ještě nenaběhla nebo už spadla.
        print(f"  ! spojení s aplikací selhalo: {e}", file=sys.stderr)
    finally:
        try:
            klient.close()
        except OSError:
            pass


def main():
    if not (os.path.exists(CERT) and os.path.exists(KEY)):
        sys.exit("Chybí certifikát. Spusť nejdřív ./nastav_https.sh")

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(POSLOUCHAT)
    server.listen(64)

    print(f"TLS proxy: https://0.0.0.0:{POSLOUCHAT[1]} → http://{APLIKACE[0]}:{APLIKACE[1]}")
    print("Telefon při prvním otevření potvrdí certifikát (Pokročilé → Pokračovat).")

    while True:
        try:
            raw, _ = server.accept()
        except OSError:
            continue
        try:
            # Handshake děláme až ve vlákně, aby jedno pomalé nebo rozbité
            # spojení nezablokovalo přijímání dalších.
            threading.Thread(
                target=lambda s=raw: obsluz(ctx.wrap_socket(s, server_side=True)),
                daemon=True,
            ).start()
        except OSError:
            raw.close()


if __name__ == "__main__":
    main()

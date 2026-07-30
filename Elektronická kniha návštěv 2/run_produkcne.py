#!/usr/bin/env python3
"""Produkční spuštění pod WSGI serverem (waitress).

Proč ne `python3 backend_v2.py`: ten startuje vývojový server Flasku, který sám
při každém běhu varuje, že do produkce nepatří — je jednovláknový a neřeší
zátěž ani chyby tak, jak by měl. Waitress je plnohodnotný WSGI server, čistě
v Pythonu, bez konfigurace.

Pozor na HTTPS: waitress sám TLS nedělá. Pro sken z telefonu (kde HTTPS musí
být, jinak prohlížeč nepustí kameru) je správná volba:

    ./nastav_https.sh && EPT_HTTPS=1 python3 backend_v2.py

Tenhle spouštěč je pro nasazení za reverzní proxy (nginx/Caddy), která TLS
ukončí — tam je waitress na místě a certifikát řeší proxy.
"""
import os

from waitress import serve

# Import backendu spustí i init_db() a předehřátí OCR — obojí je záměrně
# na úrovni modulu právě proto, aby to fungovalo i pod WSGI, kde se
# `if __name__ == "__main__"` nikdy nespustí.
from backend_v2 import app, zakladni_url

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    print("=" * 58)
    print("  Návštěvní kniha — produkční server (waitress)")
    print(f"  recepce:  {zakladni_url()}/")
    print(f"  sken:     {zakladni_url()}/sken")
    if os.environ.get("EPT_HTTPS") != "1":
        print()
        print("  Bez HTTPS. Kamera na telefonu nepojede — pro sken z telefonu")
        print("  použij: ./nastav_https.sh && EPT_HTTPS=1 python3 backend_v2.py")
    print("=" * 58)
    serve(app, host="0.0.0.0", port=port, threads=8)

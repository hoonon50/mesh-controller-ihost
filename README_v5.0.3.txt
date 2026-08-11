OpenWRT MESH CONTROLLER PRO v5.0.3
==================================

OPRAVA LIVE TOPOLOGIE
- v5.0.1 a v5.0.2 pouze ladily existující browser timery; to nemuselo obnovit skutečný zdroj dat.
- v5.0.3 proto používá vlastní backend collector a vlastní API:
    GET /api/v503/live-topology
- iHost paralelně načítá všech 5 routerů přes SSH každých 5 sekund.
- Data se cachují na backendu. Více otevřených browserů tedy nezakládá další SSH polling.
- Browser každých 5 s pouze čte hotový JSON a přímo překreslí topologii.

AKTUALIZUJE SE
- ONLINE/OFFLINE každého uzlu
- počet klientů na jednotlivých uzlech
- globální ONLINE ROUTERY / MESH SPOJE / KLIENTI / 2.4 GHz / 5 GHz / OBNOVENO
- skutečné 802.11s mesh spoje
- dBm každého spoje
- aktuální bitrate Mbit/s
- CPU a UPTIME (publikace každých 15 s)

GRAFIKA
- Původní panel TOPOLOGIE zůstává na stejném místě.
- v5.0.3 do jeho datové části položí vlastní řízenou live vrstvu.
- ROUTER je uprostřed, MESH1..4 v rozích; čáry a štítky jsou renderované přímo z nového API.
- Bez MutationObserveru.

ZATÍŽENÍ
- pouze jeden collector v iHost Dockeru
- 5 paralelních SSH čtení každých 5 s (jedno na každý router)
- CPU/uptime jsou součást stejného SSH čtení, nevytváří další SSH relace
- WAN polling 30 s a zápis WAN na SD 1x/h zůstávají beze změny

V5 OPERATION MANAGER
- persistentní REBOOT/OWUT z v5.0.0 zůstává beze změny
- rolling pořadí MESH2 -> MESH3 -> MESH4 -> MESH1 -> ROUTER zůstává

POZNÁMKA K NASAZENÍ
- ZIP je update vrstva pro stávající GitHub repository; existující app.py/templates a starší patch soubory nemažte.
- Dockerfile v5.0.3 už nespouští v501_refresh_tune.py ani v502_live_refresh_patch.py.

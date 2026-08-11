OpenWRT MESH CONTROLLER PRO v5.0.2
==================================

OPRAVA LIVE REFRESH TOPOLOGIE
-----------------------------
v5.0.1 hledala casovace podle nazvu funkci/konstant. Pokud mel puvodni dashboard
obecne pojmenovany callback, nemusel byt nalezen.

v5.0.2 pouziva jinou strategii:
- v502_live_refresh_bootstrap.js se vlozi jako PRVNI script v <head>,
- zachyti skutecne registrace window.setInterval() dalsich dashboard skriptu,
- periodicke dashboard intervaly >= 8 s jsou zkraceny na 5 s,
- callbacky, ktere primo obsahuji CPU/uptime/temperature/health, pouziji 15 s,
- setTimeout se nemeni (bezpecnost rebootu/OWUT/jednorazovych akci),
- WAN usage a WAN historie zustavaji 30 s,
- Operation Manager zustava 2 s.

TIMING
------
TOPOLOGIE / MESH SPOJE / RSSI / LINK SPEED / KLIENTI: 5 s
CPU / UPTIME:                                            15 s
WAN DOWNLOAD / UPLOAD:                                   30 s
WAN HISTORIE:                                            30 s
OPERATION MANAGER:                                        2 s
WAN ZAPIS NA SD:                                          1 h

DIAGNOSTIKA
-----------
V konzoli prohlizece lze zobrazit:
  window.__MESH_V502_REFRESH__

Objekt ukazuje, kolik skutecnych setInterval registraci bylo zkraceno a z jakeho
scriptu pochazely. Build take vytvori /app/v502_refresh_report.json.

BEZ ZMENY
---------
Persistentni REBOOT/OWUT v5.0.0, WAN pocitadlo, mesicni historie, zalohy,
Gmail reporty a rozlozeni dashboardu zustavaji zachovane.

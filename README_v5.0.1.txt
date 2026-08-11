OpenWRT MESH CONTROLLER PRO v5.0.1
==================================

LIVE REFRESH TOPOLOGIE
----------------------
Cilem je zivejsi topologie bez navratu k problemu s blikajicimi kartami.

Nove cilove intervaly:
- TOPOLOGIE / mesh spoje / rychlosti / signal: 5 s
- klienti a pocty klientu v topologii: 5 s
- CPU teplota routeru: 15 s
- UPTIME routeru: 15 s

Beze zmeny:
- Persistent Operation Manager: 2 s
- WAN DOWNLOAD/UPLOAD: 30 s
- WAN mesicni historie: 30 s
- zapis WAN statistik na SD: 1x za hodinu

TECHNICKY
---------
v501_refresh_tune.py bezi pri Docker buildu AZ po puvodnim refresh_patch.py.
Meni pouze casovace, ktere lze bezpecne rozpoznat podle nazvu funkce/konstanty
(topology/mesh/client nebo cpu/uptime/health). Operation Manager a WAN pollery
jsou z upravy vyslovne vylouceny.

Pokud v budoucnu zdrojovy refresh helper zmeni jmena natolik, ze ho patch
bezpecne nerozpozna, build nespadne a vypise WARNING misto agresivniho zasahu.

Vsechny funkce v5.0.0 (persistentni REBOOT + OWUT, resume po vypadku, zalohy,
Gmail reporty) zustavaji zachovane.

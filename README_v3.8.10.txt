OpenWRT MESH CONTROLLER PRO v3.8.10
=================================

NOVINKA: CELOŽIVOTNÍ WAN DOWNLOAD / UPLOAD
- dvě velké dlaždice vpravo od hlavního nápisu v horní liště
- DOWNLOAD = RX WAN hlavního ROUTERu 192.168.30.1
- UPLOAD   = TX WAN hlavního ROUTERu 192.168.30.1
- skutečné WAN zařízení se zjišťuje automaticky přes ubus/ifstatus
- hodnoty se zobrazují vždy na 2 desetinná místa
- do 999.99 GB se zobrazuje GB, od 1000 GB se automaticky přepne na TB
- používá desetinné jednotky: 1 GB = 1 000 000 000 B, 1 TB = 1000 GB
- nasčítaná data jsou v /data/wan_usage.json (persistentní Docker volume)
- restart routeru, iHostu nebo aktualizace kontejneru nasčítaný součet nevynuluje
- při dočasném výpadku routeru se poslední součet zachová
- čtení WAN probíhá každých 30 sekund
- počítání začíná prvním úspěšným načtením po instalaci v3.8.10; starší historická data nelze zpětně zjistit

Zachováno z v3.8.8:
- pořadí OWUT: MESH2 .3 -> MESH3 .4 -> MESH4 .5 -> MESH1 .2 -> ROUTER .1
- iHost může být LAN kabelem připojen do MESH1 .2
- před ROUTERem .1 kontrola návratu MESH1 .2 a dostupnosti ROUTERu .1
- všechny bezpečnostní funkce OWUT, zálohy, Gmail reporty a USB extroot


UI FIX v3.8.10:
- WAN dlaždice mají pevnou výšku 50 px a nepřesahují spodní hranu horního panelu.
- DOWNLOAD/UPLOAD zůstávají vpravo od hlavního nápisu.
- Třetí řádek WAN · ROUTER .1 je vizuálně skrytý, informace zůstává v tooltipu.

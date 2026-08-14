OpenWRT MESH CONTROLLER PRO v6.3.3

LIVE LAN PORTY
--------------
- LAN1–LAN4 UP/DOWN a rychlost jsou nyní součástí stejného 5s live vzorku jako topologie.
- Stav se čte přímo z /sys/class/net/lanX/{operstate,carrier,speed} na každém OpenWrt uzlu.
- Čtení je přidáno do již existujícího live SSH příkazu; nevzniká další SSH session.
- Browser aktualizuje existující LAN dlaždice na místě, bez jejich nahrazování.
- Po případném starém 30s překreslení portsGrid se poslední live stav okamžitě znovu aplikuje.

KOMPATIBILITA
-------------
- 1× klik na UP port: zařízení/IP/hostname/MAC.
- DOWN a BLOKOVÁN: 1× klik nic neotevírá.
- 2× klik: stávající runtime blokování/povolení.
- BLOKOVÁN zůstává červený se samostatným malým odznakem.
- CHRÁNĚN · iHOST a CHRÁNĚN · HASSIO zůstávají beze změny.
- v6.3.2 aktivní MAC→IPv4 resolver zůstává zachovaný.

BEZPEČNOST A DATA
-----------------
- žádná změna UCI ani /etc/config/network
- žádné nové zápisy na SD
- persistentní /data a lan_port_state.json se zachovávají

IMAGE
-----
GHCR tagy:
- latest
- 6.3.3

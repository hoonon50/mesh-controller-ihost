OpenWRT MESH CONTROLLER PRO v6.3.0
==================================

Novinka: informace o zařízeních na konkrétním fyzickém LAN portu.

OVLÁDÁNÍ LAN DLAŽDIC
--------------------
- 1× klik na LAN1–LAN4 = zobrazí zařízení nalezená na tomto fyzickém portu
- 2× klik = zachované okamžité BLOKOVÁN / POVOLENÍ portu z v6.2.0
- 1× klik funguje i na chráněném portu iHOST/HASSIO
- při dvojkliku se informační 1× klik zruší, aby se panel zbytečně neotevíral

DETEKCE ZAŘÍZENÍ
----------------
- bridge FDB určí MAC adresy skutečně viděné na konkrétním lanX
- ARP/neighbor doplní IPv4 adresu
- DHCP lease a již známí klienti Controlleru doplní hostname
- pokud je za portem switch, může panel zobrazit více zařízení
- u 192.168.30.186 se zobrazuje iHOST
- u 192.168.30.223 se zobrazuje HASSIO
- pokud IP nebo hostname nejsou známé, panel zobrazí dostupné údaje a MAC

BEZPEČNOST A BLOKOVÁNÍ
----------------------
- žádná změna OpenWrt UCI konfigurace
- v6.2.0 runtime blokování přes ip link zůstává beze změny
- /data/lan_port_state.json zůstává zdrojem uloženého stavu blokací
- watchdog po rebootu routeru znovu aplikuje uložené blokace
- port s iHOST 192.168.30.186 nebo HASSIO 192.168.30.223 zůstává chráněný proti blokování

Release zachovává stabilní topologii, klienty, LAN TTL, WAN statistiky, OWUT, zálohy a Operation Manager z předchozí verze.

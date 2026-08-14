OpenWRT MESH CONTROLLER PRO v6.3.1
==================================

LAN / TOPOLOGY INSPECTOR
------------------------
- 1× klik na LAN port funguje pouze pokud je port UP
- DOWN ani BLOKOVÁN port informační panel neotevře
- 2× klik na LAN port dál okamžitě blokuje / povoluje port
- 1× klik na online ROUTER / MESH dlaždici v TOPOLOGII zobrazí klienty uzlu

TOPOLOGIE – SKUPINY KLIENTŮ
---------------------------
- Wi-Fi 5 GHz
- Wi-Fi 2.4 GHz
- LAN1
- LAN2
- LAN3
- LAN4

Prázdné skupiny se nezobrazují. Každý klient zobrazuje IP adresu, hostname a MAC.
Wi-Fi klienti vycházejí z živých hostapd dat používaných topologií. LAN klienti
se při otevření panelu přiřadí na konkrétní fyzický port pomocí bridge FDB.
ARP/neighbor, DHCP leases a známí klienti Controlleru doplňují IP a hostname.

BEZPEČNOST / PERSISTENCE
------------------------
- žádná UCI změna ani zápis do /etc/config/network
- stávající ochrana iHOST 192.168.30.186 a HASSIO 192.168.30.223 zůstává
- stav LAN blokací zůstává v /data/lan_port_state.json
- persistentní /data z předchozí verze se zachovává

Release publikuje GHCR tagy :latest a :6.3.1.

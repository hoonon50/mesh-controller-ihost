OpenWRT MESH CONTROLLER PRO v6.3.2

AKTIVNÍ MAC -> IPv4 RESOLVER
----------------------------
Tato verze řeší situaci, kdy je klientská MAC známá jako aktivní na Wi-Fi nebo LAN,
ale popup nedokázal zobrazit její IPv4 adresu.

Postup resolveru:
1. použije aktuální ip neigh / ARP tabulku hlavního routeru,
2. použije aktivní DHCP leases,
3. použije již známý snapshot klientů Controlleru,
4. pokud MAC stále nemá IPv4, hlavní router provede krátký aktivní ping sweep
   své /24 LAN, aby se znovu naplnila ARP/neighbour tabulka,
5. MAC se znovu spáruje s nalezenou IPv4.

VLASTNOSTI
----------
- funguje pro TOPOLOGII i LAN port inspector
- aktivní sweep se spouští pouze při nalezené MAC bez IPv4
- sweep je rate-limitovaný nejvýše na 1x za 60 sekund
- úspěšné MAC -> IPv4 výsledky se krátce drží pouze v RAM
- nic nového se nezapisuje na SD
- žádná UCI konfigurace OpenWrt se nemění
- stávající 2x klik BLOKOVÁN / POVOLENÍ LAN portu se nemění
- ochrana iHOST/HASSIO se nemění

OMEZENÍ
-------
Pokud klient skutečně ještě žádnou IPv4 nemá (například čeká na DHCP, DHCP selhalo
nebo používá pouze IPv6), Controller IPv4 nevymýšlí. V běžném provozu 192.168.30.0/24
by ale aktivní resolver měl odstranit většinu případů, kdy byla IP pouze nedohledaná.

IMAGE
-----
GHCR tagy: latest a 6.3.2
Cíl: linux/arm/v7
Persistentní data: /data beze změny

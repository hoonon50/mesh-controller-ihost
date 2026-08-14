OpenWRT MESH CONTROLLER PRO v6.3.0 – SONOFF iHost ARMv7

Web: http://IP_IHOST:8088
Docker síť: host
Persistentní data: /data
Cílová architektura: linux/arm/v7
GHCR: ghcr.io/hoonon50/mesh-controller-ihost

HLAVNÍ FUNKCE
--------------
- živý stav 5 OpenWrt uzlů přes SSH/Paramiko
- 802.11s mesh topologie, RSSI a bitrate spojů
- živí Wi-Fi klienti z hostapd UBUS po jednotlivých BSS/AP
- oddělené počty 2.4 GHz / 5 GHz / LAN / celkem
- LAN klienti z fyzického FDB s 45s stabilizací pouze v RAM
- LAN port control: 2× klik = runtime BLOKOVÁN / POVOLENÍ bez UCI změn
- LAN port inspector: 1× klik = IP / hostname / MAC zařízení na konkrétním LAN portu
- chráněné porty pro iHOST 192.168.30.186 a HASSIO 192.168.30.223
- iHOST CPU / RAM / TEMP
- DATA a OBNOVENO v horním headeru
- WAN DOWNLOAD / UPLOAD a měsíční/roční historie
- persistentní WAN data v /data/wan_usage.json
- zálohy všech routerů do /data/backups + ZIP download
- PING MESH, reboot, OWUT a rolling update operace
- perzistentní operation manager v /data/mesh_operation.json
- Wi-Fi AP inactivity policy max_inactivity=60 / skip_inactivity_poll=0
- GitHub Actions build pro linux/arm/v7 a publikace do GHCR

LIVE INTERVALY
--------------
- topologie / klienti / mesh spoje: 5 s
- LAN blokovací watchdog: 5 s
- kontrola chráněných iHOST/HASSIO portů: 30 s
- CPU / uptime routerů: 15 s
- WAN: 30 s
- WAN persistence na disk: 1x za hodinu + graceful flush

VERZE v6.3.0
------------
- 1× klik na LAN1–LAN4 otevře informační panel zařízení na portu
- bridge FDB určí MAC adresy na konkrétním fyzickém lanX
- ARP/neighbor doplní IPv4 adresu
- DHCP lease a známí klienti Controlleru doplní hostname
- port se switchem může zobrazit více zařízení
- 2× klik dál okamžitě blokuje/povoluje port podle v6.2.0
- 1× klik funguje i pro CHRÁNĚN · iHOST a CHRÁNĚN · HASSIO
- OpenWrt UCI konfigurace se při blokování nemění
- GitHub Actions publikuje :latest a :6.3.0
- docker-compose lokální image tag je 6.3.0

DŮLEŽITÉ PŘI AKTUALIZACI
------------------------
Persistentní /data volume ponechte beze změny. Existující /data/config.json,
/data/backups, /data/wan_usage.json, /data/mesh_operation.json a
/data/lan_port_state.json se zachovávají.

SSH BEZPEČNOST
--------------
Aktualizace kvůli zpětné kompatibilitě nemění uložené SSH údaje v
/data/config.json ani současný runtime fallback. Pokud je na routerech stále
výchozí nebo slabé heslo, změňte ho a upravte odpovídající SSH konfiguraci iHostu.
Soubor config.example.json používá pouze zástupnou hodnotu CHANGE_ME.

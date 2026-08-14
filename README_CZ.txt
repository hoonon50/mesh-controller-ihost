OpenWRT MESH CONTROLLER PRO v6.1.0 – SONOFF iHost ARMv7

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
- CPU / uptime routerů: 15 s
- WAN: 30 s
- WAN persistence na disk: 1x za hodinu + graceful flush

VERZE v6.1.0
------------
- cleanup release nad stabilní v6.0.9
- bez změny klientské, LAN, WAN, OWUT ani reboot logiky
- sjednocen runtime backend/frontend na 6.1.0
- sjednoceny cache tagy webových assetů na 6.1.0
- GitHub Actions publikuje :latest a :6.1.0
- docker-compose lokální image tag je 6.1.0
- aktualizována hlavní dokumentace
- config.example.json už neobsahuje ukázkové heslo root/root

DŮLEŽITÉ PŘI AKTUALIZACI
------------------------
Persistentní /data volume ponechte beze změny. Existující /data/config.json,
/data/backups, /data/wan_usage.json a /data/mesh_operation.json se zachovávají.

SSH BEZPEČNOST
--------------
Existující instalace v6.1.0 kvůli zpětné kompatibilitě nemění uložené SSH údaje
v /data/config.json ani současný runtime fallback. Pokud je na routerech stále
výchozí nebo slabé heslo, změňte ho a upravte odpovídající SSH konfiguraci iHostu.
Soubor config.example.json používá pouze zástupnou hodnotu CHANGE_ME.

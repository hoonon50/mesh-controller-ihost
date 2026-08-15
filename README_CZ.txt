OpenWRT MESH CONTROLLER PRO v6.3.4 – SONOFF iHost ARMv7

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
- fyzický stav LAN1–LAN4 UP/DOWN + rychlost v 5s live cyklu
- LAN port control: 2× klik = runtime BLOKOVÁN / POVOLENÍ bez UCI změn
- LAN port inspector: 1× klik pouze na UP port = IP / hostname / MAC zařízení
- topology inspector: 1× klik na ROUTER/MESH = klienti po Wi-Fi pásmu a LAN1–LAN4
- aktivní MAC→IPv4 resolver pro klienty, kterým běžné tabulky IP nedoplnily
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
- topologie / klienti / mesh spoje / LAN1–LAN4 fyzický stav: 5 s
- LAN blokovací watchdog: 5 s
- kontrola chráněných iHOST/HASSIO portů: 30 s
- CPU / uptime routerů: 15 s
- WAN: 30 s
- WAN persistence na disk: 1x za hodinu + graceful flush
- aktivní MAC→IPv4 sweep nejvýše 1x za 60 s a pouze při nalezené MAC bez IPv4
- během OWUT čekání heartbeat do operačního logu přibližně každých 30 s

VERZE v6.3.4
------------
- oprava falešného STARTED při automatickém/ručním OWUT upgradu
- background launcher už nezávisí na externím příkazu nohup
- child shell ignoruje SIGHUP přímo přes BusyBox/POSIX ash `trap '' HUP`
- při startu se vytváří /tmp/mesh-owut.pid a /tmp/mesh-owut.log
- po 2 sekundách se ověří, že proces skutečně běží nebo už vytvořil exit kód
- pokud launcher selže, operace skončí během několika sekund místo čekání 20 minut
- watchdog kontroluje PID, exit kód a poslední řádky OWUT logu
- během dlouhého buildu zapisuje stav `OWUT běží MM:SS / 20:00` a poslední relevantní řádek logu
- timeout nyní obsahuje poslední dostupné řádky OWUT logu pro diagnostiku
- automatický Gmail report zůstává zachovaný i při chybě OWUT
- v6.3.3 live LAN porty, blokování, ochrana iHOST/HASSIO a klientské inspektory se nemění
- žádné nové zápisy do OpenWrt UCI a žádné nové pravidelné zápisy na SD
- GitHub Actions publikuje :latest a :6.3.4
- docker-compose lokální image tag je 6.3.4

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

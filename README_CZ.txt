OpenWRT MESH CONTROLLER PRO v6.3.8 – SONOFF iHost ARMv7

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

VERZE v6.3.8
------------
- opravuje automatický návrat USB Extrootu po skutečném OWUT/sysupgrade hlavního ROUTERu
- ruší příliš přísný first-boot package gate z v6.3.6, který mohl zablokovat potřebný druhý reboot
- po prvním interním bootu se po stabilním SSH čeká 15 s a provede se standardní druhý reboot bez změny fstab
- po druhém bootu se ověří, že /overlay běží z USB a UUID přesně odpovídá živému UUID uloženému před sysupgrade
- pokud je i po druhém bootu stále interní overlay, automatický fallback ověří původní USB disk podle přesného UUID a TYPE=ext4
- fallback zapisuje pouze interní fstab.extroot: target /overlay, původní UUID, fstype ext4, enabled=1
- po fallback opravě se provede třetí reboot a znovu se ověří USB /overlay a přesné UUID
- USB disk se nikdy neformátuje, nemaže, nereparticionuje ani se na něj nekopíruje nový overlay
- pokud není sysupgrade dostupný, no-update větev stále neprovádí žádný reboot ani zápis do Extrootu
- OWUT/sysupgrade pořadí zůstává MESH2 -> MESH3 -> MESH4 -> MESH1 -> ROUTER
- běžný reboot z v6.3.7 zůstává MESH2 -> MESH3 -> MESH4 -> ROUTER -> MESH1
- Gmail reporty nadále používají označení iHost teplota
- GitHub Actions publikuje :latest a :6.3.8
- docker-compose lokální image tag je 6.3.8

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

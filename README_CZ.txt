OpenWRT MESH CONTROLLER PRO v6.3.5 – SONOFF iHost ARMv7

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

VERZE v6.3.5
------------
- oprava bezpečného návratu USB Extrootu na hlavním ROUTERu po OWUT sysupgrade
- před sysupgrade musí být /overlay skutečně na /dev/sd* a musí být dostupné jeho živé UUID
- UUID se nikdy nehardcoduje; bere se z aktuálně připojeného USB overlaye těsně před aktualizací
- po prvním sysupgrade bootu Controller zjistí, zda ROUTER běží z interního rootfs_data/UBIFS nebo už z USB
- pokud je první boot interní, Controller zapíše do právě aktivního interního /etc/config/fstab sekci fstab.extroot s uloženým UUID, target=/overlay, fstype=ext4 a enabled=1
- zapsaná interní Extroot konfigurace se přes SSH okamžitě ověří ještě PŘED druhým rebootem
- pokud USB s očekávaným UUID není vidět nebo kontrola fstab selže, druhý reboot se bezpečně neprovede a ROUTER zůstane dostupný na interním overlayi
- teprve po ověření interního fstab se provede druhý reboot požadovaný OpenWrt pro Extroot po sysupgrade
- po druhém bootu musí být /overlay na USB a UUID musí přesně odpovídat hodnotě před aktualizací
- při selhání se do reportu přidá diagnostika overlay / fstab / block info / extroot boot log
- pokud je USB Extroot aktivní už po prvním bootu a UUID sedí, zbytečný druhý reboot se neprovádí
- v6.3.4 OWUT launcher s PID/log/heartbeat zůstává beze změny
- v6.3.3 live LAN porty, blokování, ochrana iHOST/HASSIO a klientské inspektory se nemění
- žádné periodické UCI zápisy; jediný servisní UCI zápis je obnova interního fstab během ROUTER sysupgrade mezi prvním a druhým bootem
- GitHub Actions publikuje :latest a :6.3.5
- docker-compose lokální image tag je 6.3.5

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

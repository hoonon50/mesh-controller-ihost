OpenWRT MESH CONTROLLER PRO v6.3.9 – SONOFF iHost ARMv7

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

VERZE v6.3.9
------------
- opravuje duplicitní automatický OWUT scheduler, který mohl spustit starou upgrade cestu z owut_manager.py
- jediným vlastníkem automatického OWUT plánování je nyní PersistentMeshOperationManager
- legacy _scheduler_loop v owut_manager.py je hard-disabled a jeho owut-scheduler thread se vůbec nespouští
- nastavení plánování /data/owut_settings.json zůstává zachované; persistent scheduler používá stejná uživatelská nastavení
- starý POST /api/owut/upgrade zůstává kvůli kompatibilitě, ale už nespouští legacy _upgrade_worker; deleguje na persistent manager
- tím je odstraněna stará automatická cesta, která po prvním interním bootu ROUTERu používala first-boot package gate a mohla zrušit nutný Extroot reboot
- bezpečný Extroot flow z v6.3.8 zůstává aktivní: standardní druhý reboot bez změny fstab, přesná kontrola původního UUID a fallback pouze do interního fstab.extroot
- USB disk se při recovery nikdy neformátuje, nemaže, nereparticionuje ani se na něj nekopíruje nový overlay
- pokud není sysupgrade dostupný, no-update větev neprovádí reboot ani zápis do Extrootu
- OWUT/sysupgrade pořadí zůstává MESH2 -> MESH3 -> MESH4 -> MESH1 -> ROUTER
- běžný reboot zůstává MESH2 -> MESH3 -> MESH4 -> ROUTER -> MESH1
- Operation Manager UI zobrazuje verzi v6.3.9
- GitHub Actions publikuje :latest a :6.3.9
- docker-compose lokální image tag je 6.3.9

DŮLEŽITÉ PŘI AKTUALIZACI
------------------------
Persistentní /data volume ponechte beze změny. Existující /data/config.json,
/data/backups, /data/wan_usage.json, /data/mesh_operation.json,
/data/mesh_scheduler_v500.json, /data/owut_settings.json a
/data/lan_port_state.json se zachovávají.

Po aktualizaci Controlleru se kontejner musí restartovat, aby starý již běžící
owut-scheduler thread zmizel. Nový image v6.3.9 už tento thread nevytváří.

SSH BEZPEČNOST
--------------
Aktualizace kvůli zpětné kompatibilitě nemění uložené SSH údaje v
/data/config.json ani současný runtime fallback. Pokud je na routerech stále
výchozí nebo slabé heslo, změňte ho a upravte odpovídající SSH konfiguraci iHostu.
Soubor config.example.json používá pouze zástupnou hodnotu CHANGE_ME.

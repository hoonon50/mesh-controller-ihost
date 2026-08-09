OpenWrt Mesh Controller PRO WEB v3.2 – SONOFF iHost ARMv7

Web: http://IP_IHOST:8088
Docker síť: host
Persistentní data: /data
Cílová architektura: linux/arm/v7

Funkce:
- živý stav 5 OpenWrt uzlů přes SSH/Paramiko
- 802.11s mesh topologie + RSSI
- Wi-Fi klienti
- potvrzené LAN klienty z FDB/brctl
- ARP-only zařízení jako Neurčené
- fyzické LAN porty a rychlost
- automatický refresh
- aktivní scan LAN
- ping všech uzlů
- záloha wireless/network/dhcp/dawn do /data/backups
- restart všech routerů
- LED OFF/ON/default
- stav USB overlay / package manageru hlavního uzlu
- aktualizace balíčků všech routerů
- diagnostický log v /data/mesh-controller.log

ZMĚNY v3.2
-----------
- SAFE MESH zůstává úplně odstraněný
- odstraněn SSH terminál z v3.1
- přidán samostatný panel „Průběh operace“
- progress bar 0–100 % pro delší operace
- živý stav jednotlivých routerů: ČEKÁ / PROBÍHÁ / HOTOVO / CHYBA
- živý čas průběhu operace
- živý provozní log dané operace
- progress funguje pro obnovení stavu, aktivní scan, ping, zálohu, LED, aktualizaci balíčků a restart
- během dlouhé operace jsou ostatní akční tlačítka zablokovaná, aby se operace nekřížily
- automatický refresh se během dlouhé operace dočasně neprovádí
- topologie je roztažená na větší plochu: hlavní uzel uprostřed, 4 satelity více u krajů
- větší a čitelnější karty uzlů a štítky spojů

Persistentní volume /data ponechte při aktualizaci stejné.
Staré položky terminal_pin / terminal_timeout v existujícím /data/config.json nevadí; v3.2 je ignoruje.

Záměrně zatím nepřeneseno:
- USB overlay vytvoření/deaktivace (destruktivní práce s diskem)
- plný Wi-Fi editor jednotlivých UCI rozhraní
- grafické přetahování pozic uzlů a editor uplinků v UI

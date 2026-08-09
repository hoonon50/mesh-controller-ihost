OpenWrt Mesh Controller PRO WEB v3.0 – první Docker verze

Web: http://IP_ZARIZENI:8088
Docker síť: host
Persistentní data: /data
Cílová architektura iHost: linux/arm/v7

Přenesené funkce:
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
- SAFE MESH s povinnou zálohou před nasazením
- diagnostický log v /data/mesh-controller.log

Záměrně zatím nepřeneseno:
- USB overlay vytvoření/deaktivace (destruktivní práce s diskem – přeneseme po ověření základní verze)
- plný Wi-Fi editor jednotlivých UCI rozhraní
- grafické přetahování pozic uzlů a editor uplinků v UI

První start automaticky vytvoří /data/config.json.

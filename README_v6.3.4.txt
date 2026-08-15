OpenWRT MESH CONTROLLER PRO v6.3.4
==================================

OWUT launcher reliability hotfix.

Co je opraveno:
- background OWUT už nepoužívá externí nohup
- child shell ignoruje SIGHUP pomocí `trap '' HUP`
- launcher zapisuje PID do /tmp/mesh-owut.pid
- /tmp/mesh-owut.log vznikne ještě před spuštěním procesu
- po 2 s se ověřuje, zda proces skutečně žije nebo vytvořil exit kód
- falešný STARTED tedy nenechá Controller čekat 20 minut
- watchdog kontroluje PID + exit + log
- při dlouhém buildu zapisuje heartbeat každých přibližně 30 s
- heartbeat ukazuje uplynulý čas vůči 20minutovému limitu a poslední řádek OWUT logu
- timeout vrací poslední log pro diagnostiku

Nemění se:
- pořadí a bezpečnost OWUT preflightu/záloh
- žádný --force
- automatický Gmail report
- USB extroot ochrana hlavního ROUTERu
- LAN blokování a ochrana iHOST/HASSIO
- live LAN porty v6.3.3
- klientské inspektory a MAC→IPv4 resolver
- OpenWrt UCI konfigurace

Image:
- ghcr.io/hoonon50/mesh-controller-ihost:latest
- ghcr.io/hoonon50/mesh-controller-ihost:6.3.4

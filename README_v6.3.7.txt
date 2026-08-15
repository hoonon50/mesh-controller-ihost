OpenWRT MESH CONTROLLER PRO v6.3.7
==================================

ZMĚNA POŘADÍ POUZE PRO BĚŽNÝ REBOOT
------------------------------------
Běžný rolling reboot všech uzlů nově používá:

MESH2 -> MESH3 -> MESH4 -> ROUTER -> MESH1

Důvod: iHost je fyzicky připojený LAN k MESH1. MESH1 se proto restartuje až úplně poslední, kdy už hlavní ROUTER, DHCP, DNS a gateway znovu běží. Po návratu linku se iHost připojuje do už hotové sítě.

OWUT / SYSUPGRADE
-----------------
Pořadí OWUT/sysupgrade se NEMĚNÍ:

MESH2 -> MESH3 -> MESH4 -> MESH1 -> ROUTER

Bezpečnostní Extroot logika v6.3.5/v6.3.6 zůstává beze změny.
Scheduler automatických OWUT aktualizací se v této verzi nemění.

REPORTY
-------
V Gmail reportech se označení "iHost CPU / SoC" zjednodušuje na:

iHost teplota

Samotné měření teploty z v6.3.6 se nemění.

TECHNICKY
---------
- oddělený REBOOT_ORDER pro běžný reboot
- UPDATE_ORDER / OWUT pořadí zůstává beze změny
- změna platí pro Persistent Operation Manager i /api/owut/reboot target=all
- žádné změny OpenWrt UCI, Wi-Fi, DHCP ani Extroot konfigurace
- /data zůstává beze změny
- GHCR tagy: latest + 6.3.7

OpenWRT MESH CONTROLLER PRO v6.0.4
==================================

KLIENTI / LAN – OPRAVA STABILITY
- 2.4 GHz a 5 GHz zůstávají živé přes hostapd a aktualizují se po 5 s.
- LAN klienti jsou nadále pouze potvrzené dynamické MAC z fyzického LAN/ETH portu (bridge FDB).
- Krátké zmizení LAN MAC z dynamické FDB tabulky už neshodí celkové KLIENTI.
- LAN MAC má 45s paměť pouze v RAM iHostu; na SD kartu se kvůli tomu nic nezapisuje.
- Pokud se stejná MAC objeví na Wi-Fi, Wi-Fi má okamžitě přednost a LAN záznam se odstraní.
- Jedna LAN MAC má právě jednoho vlastníka/router, takže se při přesunu neduplikuje.
- KLIENTI = unikátní 2.4 GHz + 5 GHz + stabilizované potvrzené LAN MAC.

NOVÁ HORNÍ DLAŽDICE
- Do souhrnné lišty je přidána samostatná dlaždice LAN.
- LAN ukazuje stejný stabilizovaný počet, který vstupuje do celkového KLIENTI.
- Díky tomu je hned vidět, zda změna celkového počtu pochází z Wi-Fi nebo LAN.

BEZE ZMĚNY
- MESH spoje/dBm/rychlosti: 5 s.
- CPU/UPTIME: 15 s.
- WAN: 30 s, persistence na SD 1x za hodinu.
- Operation Manager / OWUT / rolling reboot beze změny.
- Wi-Fi AP policy max_inactivity=60 / skip_inactivity_poll=0 beze změny.

OpenWRT MESH CONTROLLER PRO v6.0.3
==================================

OPRAVA LIVE POČTŮ KLIENTŮ V TOPOLOGII
- Opraven fallback z v6.0.2: už se při chybě jednoho hostapd dotazu nezmrazí celý Wi-Fi stav routeru.
- Cache je nově vedena po jednotlivých hostapd BSS/AP.
- Každý úspěšně načtený BSS se aktualizuje okamžitě při dalším 5s vzorku.
- Selže-li jen konkrétní BSS, poslední platný stav se zachová pouze pro tento BSS.
- Ostatní BSS na stejném routeru i druhé pásmo dál běží LIVE.
- Horní KLIENTI / 2.4 GHz / 5 GHz a počet klientů v ROUTER/MESH dlaždicích vznikají ze stejného sjednoceného vzorku.
- Platný hostapd clients={} je stále skutečných 0 klientů a propíše se okamžitě.
- Pokud BSS selže už při prvním vzorku po startu Controlleru, použije se pouze pro tento BSS `iw station dump` jako startovní fallback.
- Žádná klientská TTL 45 s se nepoužívá.

BEZE ZMĚNY
- live polling topologie 5 s
- CPU / uptime 15 s
- MESH RSSI a bitrate přes iw
- max_inactivity=60 / skip_inactivity_poll=0 policy
- Operation Manager, rolling reboot a OWUT
- WAN statistiky, historie a hodinový zápis na SD

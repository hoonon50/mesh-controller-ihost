OpenWRT MESH CONTROLLER PRO v6.0.2
==================================

OPRAVA PŘESKAKOVÁNÍ POČTU KLIENTŮ
- Opravena konkrétní chyba backendu: dočasné selhání `ubus call hostapd.<iface> get_clients` už není převáděno na platné `{}` = 0 klientů.
- Platný hostapd výsledek `clients={}` stále správně znamená skutečně 0 asociovaných klientů.
- Pokud jeden hostapd dotaz v 5s vzorku selže, pro Wi-Fi klienty daného uzlu se zachová poslední ÚSPĚŠNÝ vzorek.
- Jakmile další dotaz proběhne korektně, nové hodnoty se okamžitě použijí.
- Není zde žádná 45s klientská TTL; cache se používá pouze při technické chybě hostapd/ubus.
- 2.4 GHz, 5 GHz a CELKEM se stále deduplikují podle MAC napříč všemi uzly.

DŮVOD
Ve v6.0.1 shell používal:
  ubus call ... get_clients || printf '{}\n'
Dočasná chyba tak vypadala jako skutečně prázdný BSS a několik klientů na jeden refresh zmizelo.

BEZE ZMĚNY
- live polling 5 s
- CPU/uptime 15 s
- MESH peer RSSI/bitrate přes iw
- Wi-Fi AP policy max_inactivity=60 / skip_inactivity_poll=0
- Operation Manager / rolling reboot / OWUT
- WAN statistiky / historie / hodinový zápis na SD

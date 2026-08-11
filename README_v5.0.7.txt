OpenWRT MESH CONTROLLER PRO v5.0.7
==================================

OPRAVA LIVE KLIENTŮ
- 2.4 GHz, 5 GHz i CELKOVÝ počet klientů jsou nyní ze stejného LIVE vzorku.
- Odstraněna 45s TTL stabilizace celkového počtu klientů.
- Wi-Fi klienti se primárně získávají přes OpenWrt hostapd ubus get_clients.
- Do počtu se berou aktuálně asociované stanice (assoc != false).
- Pásmo se určuje přímo z freq vrácené hostapd (2.4 / 5 GHz).
- iw station dump zůstává pro 802.11s MESH peer RSSI/bitrate a jako fallback, pokud hostapd ubus není dostupný.
- Aktualizace klientů zůstává po 5 s.

ODOLNOST
- Při selhání celého SSH vzorku jednoho uzlu se krátce zachová poslední platný stav
  (NODE_FAILURE_GRACE=2), aby jediná SSH chyba neshodila počty na nulu.
- To není klientská TTL: při normálně dostupném routeru se odpojený klient odstraní
  v následujícím úspěšném 5s hostapd vzorku.

OSTATNÍ
- iHOST / DOWNLOAD / UPLOAD layout z v5.0.6 zůstává beze změny.
- Operation Manager, OWUT, WAN statistiky a měsíční historie beze změny.

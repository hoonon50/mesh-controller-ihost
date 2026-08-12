OpenWRT MESH CONTROLLER PRO v6.0.1
==================================

OPRAVA DVOJÍHO REFRESHU HORNÍCH DLAŽDIC
- ONLINE ROUTERY, MESH SPOJE, KLIENTI, 5 GHz, 2.4 GHz a OBNOVENO mají nyní
  jedinou VIDITELNOU hodnotu z /api/v503/live-topology.
- Původní dashboard může technicky dál aktualizovat svůj starý prvek, ale ten
  je trvale skrytý. Nemůže tedy přepisovat novou LIVE hodnotu.
- Tím se odstraní pravidelné přepínání např. KLIENTI 23 <-> 27 a vracení času
  OBNOVENO na starší hodnotu.
- LIVE backend zůstává 5 s.

HORNÍ LIŠTA
- Tlačítko OBNOVIT STAV je skryté/odstraněné z UI jako nadbytečné.
- iHOST dlaždice zůstává hned vedle názvu aplikace.
- DOWNLOAD a UPLOAD zůstávají vpravo v původní kompaktní šířce.

BEZE ZMĚNY
- live topologie / mesh spoje / dBm / rychlosti
- hostapd get_clients pro 2.4 / 5 GHz / CELKEM
- Operation Manager / rolling reboot / OWUT
- Wi-Fi AP policy max_inactivity=60 + skip_inactivity_poll=0
- WAN statistiky a hodinové ukládání na SD

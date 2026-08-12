OpenWRT MESH CONTROLLER PRO v6.0.9
==================================

REVIZE DLAZDIC / PREKRYVU
- Puvodni spodní summary panel je kompletne skryty.
- Nova viditelna summary lista ma 6 vlastnich LIVE dlazdic: ONLINE ROUTERY, MESH SPOJE, KLIENTI, 5 GHz, 2.4 GHz, LAN.
- Nova lista je v Shadow DOM, takze stary dashboard ji nemuze prepsat podle poradi prvku.
- Tím se odstranuje probliknuti ZALOHY na miste LAN a obdobne prekryvy.
- Stary dashboard muze dale aktualizovat svuj skryty DOM bez vizualniho vlivu.

HORNI HEADER
- iHOST / DATA / OBNOVENO jsou v samostatne pevne flex zone.
- DOWNLOAD / UPLOAD zustavaji samostatne napravo.
- Pri mensi sirce se header radeji zalomi, nikdy se nema prekryvat.
- DATA i OBNOVENO zustavaji napojene na stabilni backendove hodnoty.

FUNKCE
- Klientska, LAN, WAN, OWUT, reboot, Wi-Fi policy ani persistencni logika se nemeni.

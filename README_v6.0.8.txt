OpenWRT MESH CONTROLLER PRO v6.0.8
==================================

OPRAVA HEADERU DATA / OBNOVENO
- DATA a OBNOVENO jsou napevno v horní liště vedle iHOST.
- Skrývací logika spodní summary lišty hledá ZÁLOHY(/data) a OBNOVENO výhradně uvnitř spodního summary panelu.
- Nemůže tedy omylem skrýt nové horní dlaždice.
- DATA už nekopíruje hodnotu z původní DOM dlaždice. Hodnota přichází stabilně z backendu jako DATA_DIR (standardně /data).
- OBNOVENO používá clock živého backendového vzorku.

SPODNÍ LIŠTA
- ONLINE ROUTERY | MESH SPOJE | KLIENTI | 5 GHz | 2.4 GHz | LAN
- Původní ZÁLOHY(/data) a OBNOVENO zůstávají skryté pouze ve spodním panelu.

Ostatní funkce v6.0.7 se nemění.

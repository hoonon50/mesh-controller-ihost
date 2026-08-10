OpenWRT MESH CONTROLLER PRO v3.8.12
==================================

WAN DATA – HISTORIE
- Do volné spodní části pravého panelu vedle TOPOLOGIE se přidává měsíční WAN historie.
- Původní PRŮBĚH OPERACE, progress bar a log zůstávají zachované.
- Výběr roku se automaticky doplňuje podle uložené historie.
- Každý rok ukazuje LEDEN až PROSINEC:
    DOWNLOAD | UPLOAD | CELKEM
- Dole je součet celého zvoleného roku.
- Zobrazení má vždy 2 desetinná místa.
- Do 999.99 GB se používá GB, od 1000 GB se automaticky zobrazí TB.

PERSISTENCE / SD KARTA
- WAN se vzorkuje každých 30 sekund.
- Celoživotní součet i historie se drží průběžně v RAM.
- Na /data/wan_usage.json se standardně zapisuje jen jednou za hodinu.
- Historie je ve STEJNÉM souboru /data/wan_usage.json, takže nepřibyl druhý periodický zápis na SD.
- Při korektním ukončení procesu se rozpracovaný stav uloží.

MIGRACE Z v3.8.11
- Při prvním spuštění v3.8.12 se dosavadní celoživotní DOWNLOAD/UPLOAD jednorázově zařadí do aktuálního měsíce (Europe/Prague).
- Při instalaci dne 10. 8. 2026 tedy dosavadní hodnoty přejdou do SRPNA 2026.
- Následující měsíce se zakládají automaticky.

ZACHOVÁNO
- Horní kompaktní DOWNLOAD/UPLOAD dlaždice.
- OWUT, zálohy, Gmail reporty a layout zůstávají beze změny.
- Bez MutationObserveru; historie se vloží jednorázově po načtení DOM.

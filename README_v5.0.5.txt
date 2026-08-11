OpenWRT MESH CONTROLLER PRO v5.0.5
==================================

1) HORNÍ DLAŽDICE iHOST
- Nová dlaždice se vloží vlevo od DOWNLOAD a UPLOAD.
- Má stejnou výšku jako WAN dlaždice.
- Zobrazuje: CPU %, RAM %, TEMP °C.
- CPU je celkové vytížení hostu z /proc/stat.
- RAM vychází z MemTotal/MemAvailable v /proc/meminfo.
- TEMP bere nejvyšší platnou teplotu dostupnou v /sys/class/thermal nebo /sys/class/hwmon.
- Pokud Docker host thermal senzory nezpřístupní, TEMP ukáže pomlčku.
- Žádná z těchto hodnot se nezapisuje na SD; jde jen o čtení z RAM/proc/sys.

2) STABILIZACE POČTU KLIENTŮ
- v5.0.4 používala pro klienty čistý 5sekundový okamžitý snímek iw station dump + bridge FDB.
- Krátce neúplný station dump, roaming nebo jeden nepovedený SSH vzorek proto mohl udělat např. 30 -> 23 -> 30.
- v5.0.5 drží registr klientských MAC v RAM po dobu 45 sekund od posledního potvrzeného výskytu.
- Jediný chybný/neúplný vzorek klienta okamžitě nesmaže.
- Skutečně odpojený klient zmizí z počtu nejpozději po 45 s.
- Registr se NEUKLÁDÁ na SD kartu.
- Při roamingu se jedna MAC stále započítá jen jednou.

3) KRÁTKÉ SSH VÝPADKY
- Uzel se po jediném neúspěšném 5s SSH vzorku okamžitě neprohlásí za offline.
- Tolerují se 2 po sobě jdoucí chyby; mezitím je uzel označen STALE a drží poslední známá data.

ZACHOVÁNO
- live topologie 5 s
- CPU/UPTIME routerů 15 s
- WAN DOWNLOAD/UPLOAD 30 s
- WAN zápis na SD 1x/h
- Persistent Operation Manager v5

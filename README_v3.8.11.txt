OpenWRT MESH CONTROLLER PRO v3.8.11
====================================

ZMENA PRO SETRENI SD KARTY iHostu
- WAN RX/TX z ROUTERu 192.168.30.1 se dale nacita kazdych 30 sekund.
- DOWNLOAD/UPLOAD se prubezne pocita v RAM, takze dlazdice zustavaji aktualni.
- /data/wan_usage.json se standardne zapisuje pouze 1x za 3600 s (1 hodinu).
- Pri prvnim spusteni / zmene boot_id WAN routeru / resetu WAN counteru se baseline ulozi hned.
- Pri korektnim ukonceni procesu se rozpracovany soucet flushne do /data/wan_usage.json.
- Pri docasne SSH/WAN chybe se stav chyby na SD kartu nezapisuje.

Obnova po restartu kontejneru:
- Pokud ROUTER .1 mezitim nerebootoval, rozdil od posledniho ulozeneho WAN counteru se po startu znovu dopocita.
- Pri soucasnem tvrdem vypadku iHostu i ROUTERu .1 muze chybet cast provozu od posledniho hodinoveho ulozeni.

Grafika v3.8.10 zustava beze zmeny.

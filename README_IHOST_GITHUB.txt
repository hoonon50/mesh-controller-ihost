OpenWrt Mesh Controller PRO WEB v3.5 – SONOFF iHost ARMv7

Změny v3.5:
- SAFE MESH není součástí webu.
- Diagnostický log byl odstraněn; zůstal pouze živý log právě probíhající operace.
- Aktualizace balíčků se spustí okamžitě po kliknutí, bez potvrzovacího dialogu.
- Tlačítko LED výchozí bylo odstraněno; zůstává LED ON a LED OFF.
- Nápis "Stav nebyl načten" byl odstraněn.
- Topologie: uzly jsou roztažené do celé plochy; popisek mesh spoje je mimo střed linky a obsahuje pouze dBm a Mbit/s.
- Zálohy: každý router vytváří standardní OpenWrt sysupgrade -b archiv.
- Názvy:
  192.168.30.1 = ROUTER.tar.gz
  192.168.30.2 = MESH1.tar.gz
  192.168.30.3 = MESH2.tar.gz
  192.168.30.4 = MESH3.tar.gz
  192.168.30.5 = MESH4.tar.gz
- Web obsahuje seznam záloh, stažení jednotlivých .tar.gz, stažení celé sady jako ZIP a smazání sady.
- Persistentní data zůstávají v /data (volume mesh-controller-data).

Aktualizace přes GitHub:
1. Nahraj obsah tohoto balíku do stejného repository mesh-controller-ihost a přepiš existující soubory.
2. Commit do main.
3. Počkej na zelený GitHub Actions build.
4. Na iHostu stáhni/spusť nový :latest image.
5. Vždy připoj stávající volume mesh-controller-data:/data a Network=host.


v3.5 opravy:
- klienti: Wi-Fi station + bridge FDB + ARP + DHCP fallback
- zálohy: bez SFTP, binární přenos přes SSH exec; ověření gzip/tar
- topologie: bez MHz, automatické odsazení popisků od uzlů a od sebe

OpenWRT MESH CONTROLLER PRO v5.0.0
==================================

HLAVNI ZMENA
------------
REBOOT VSECH a OWUT SYSUPGRADE uz nejsou jednorazove sekvence zavisle na tom,
zda je iHost zrovna pripojen do site. V5 pouziva persistentni stavovy automat.

Stav operace:
    /data/mesh_operation.json

Po restartu Dockeru/iHostu se rozpracovana operace nacte a pokracuje od posledniho
bezpecne ulozeneho kroku. Hotove routery se znovu nerebootuji/neupgraduji.

TOPOLOGIE
---------
iHost je LAN kabelem pripojen do MESH1 192.168.30.2.
Routery mezi sebou pouzivaji bezdratovy mesh backhaul.

Bezpecne poradi:
    MESH2 192.168.30.3
      -> MESH3 192.168.30.4
      -> MESH4 192.168.30.5
      -> MESH1 192.168.30.2
      -> overeni .2 + .1
      -> ROUTER 192.168.30.1

REBOOT VSECH
------------
Pro KAZDY router:
1. stabilni SSH precheck
2. ulozeni boot_id
3. odeslani reboot
4. cekani na OFFLINE
5. cekani na stabilni ONLINE/SSH (3 kontroly)
6. overeni noveho boot_id
7. az potom dalsi router

Pri MESH1 .2:
- iHost muze ztratit sit, ale Python/Docker dal bezi lokalne
- manager pouze ceka na navrat .2
- po navratu musi byt pres SSH dostupna .2 i .1
- teprve potom se smi pokracovat na ROUTER .1

OWUT SYSUPGRADE
---------------
1. owut check --verbose na vsech 5 routerech
2. pokud nikde neni novy sysupgrade -> nic se neflashuje, pouze report
3. pokud je upgrade dostupny -> standardni sysupgrade zaloha VSECH 5 routeru do /data/backups
4. rolling OWUT ve stejnem bezpecnem poradi jako reboot
5. nikdy se nepouziva --force
6. po kazdem sysupgrade cekani na stabilni SSH a novy boot_id
7. ROUTER .1 s aktivnim USB Extroot provede druhy rizeny reboot a overi /overlay + UUID
8. finalni health check vsech 5 uzlu
9. Gmail HTML/TEXT report podle stavajiciho nastaveni

AUTOMATICKY OWUT
----------------
V5 ma vlastni scheduler a cte stavajici:
    /data/owut_settings.json

Podporuje:
- Kazdy den
- Vybrany den
- nastaveny cas

Stary OWUT scheduler je pri buildovani vypnut, aby se automaticka operace nespustila 2x.

OBNOVA PO VYPADKU
-----------------
Pokud se Docker/iHost restartuje pri:
- cekani na reboot routeru
- cekani na navrat MESH1
- OWUT buildu/sysupgrade
- navratu ROUTERu .1

v5 nacte /data/mesh_operation.json a pokusi se pokracovat. U jiz odeslane akce
se ji snazi znovu neposilat; pouziva ulozene boot_id a stav kroku.

CHYBY
-----
Sitovy timeout = PAUSED. Dalsi router se NIKDY nespusti.
Ve webu se objevi POKRACOVAT. Operaci lze bezpecne obnovit.
Fatalni chyba = ERROR. Dalsi router se NIKDY nespusti.

WEB UI
------
V panelu PRUBEH OPERACE pribude kompaktni OPERATION MANAGER v5.0.0:
- progress
- aktualni stav
- MESH2/MESH3/MESH4/MESH1/ROUTER
- POKRACOVAT pri PAUSED/ERROR
- ZASTAVIT pri bezici operaci

Tlačitka REBOOT / RESTART VSECH a OWUT AKTUALIZACE jsou ve frontend capture fazi
presmerovana na v5 API, takze stare jednorazove handlery se nespusti.

API
---
GET  /api/v500/operation
POST /api/v500/reboot
POST /api/v500/owut
POST /api/v500/resume
POST /api/v500/cancel

SD KARTA
--------
Stav operace se zapisuje pouze pri jednotlivych krocich/prechodech. Nejde o
rychly periodicky zapis. WAN statistiky zustavaji podle predchozi verze v RAM
a standardne se ukladaji 1x za hodinu.

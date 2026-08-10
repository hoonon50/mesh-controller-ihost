OpenWRT MESH CONTROLLER PRO v3.7.1
=================================

OWUT SYSUPGRADE
- stávající ruční tlačítko aktualizace je přesměrováno na OWUT
- firmware/sysupgrade se provádí přes `owut`, nikoli hromadným `apk upgrade` / `opkg upgrade`
- pořadí upgradu: MESH1 (.2) -> MESH2 (.3) -> MESH3 (.4) -> MESH4 (.5) -> ROUTER (.1)
- před upgradem proběhne `owut check --verbose` na všech pěti routerech
- pokud na všech uzlech není žádná změna, nic se neflashuje a nevytváří se zbytečná pre-upgrade záloha
- pokud je co aktualizovat, vytvoří se nejdřív záloha všech pěti routerů do `/data/backups/OWUT_...`
- automatika nikdy nepoužije `--force`; downgrade / blokující OWUT kontrola operaci zastaví
- pokud jeden satelit selže, další postup se zastaví a hlavní ROUTER .1 se neflashuje

USB EXTROOT – ROUTER 192.168.30.1
- před OWUT sysupgrade musí být USB `/overlay` aktivní
- do OWUT image pro .1 se explicitně přidávají:
  block-mount,kmod-fs-ext4,kmod-usb-storage,kmod-usb-storage-uas
- po skutečném sysupgrade .1 proběhne druhý reboot a kontrola USB `/overlay` + UUID
- pokud se USB overlay po druhém bootu nevrátí, operace skončí jako CHYBA
- automatika NIKDY sama neformátuje USB
- ruční `NASTAVIT USB OVERLAY .1` používá ověřený postup uživatele a vyžaduje přesný text `SMAZAT USB`
- ruční overlay je destruktivní: smaže první nalezený `/dev/sdX`

RESTARTY
- `RESTART VŠECH` restartuje MESH1 -> MESH4 -> ROUTER, hlavní router je poslední
- reboot je standardní OpenWrt `reboot`; OWUT se používá pro firmware/sysupgrade

AUTOMATICKÁ AKTUALIZACE
- ve výchozím stavu VYPNUTÁ
- nastavuje se den v týdnu a čas
- v termínu se spustí stejný bezpečný OWUT postup jako ručně
- bez kompletního Gmail nastavení nelze automatiku zapnout

GMAIL REPORT
- SMTP SSL `smtp.gmail.com:465`
- odesílatel, příjemce a Gmail heslo aplikace se ukládají jen do `/data/owut_settings.json`
- soubor má chmod 600 a heslo se neposílá zpět do prohlížeče
- `ODESLAT TESTOVACÍ EMAIL` ověří konfiguraci
- po ruční i automatické aktualizaci přijde report OK / CHYBA / NEDOKONČENO
- pokud je při výpadku hlavního routeru Gmail nedostupný, report se uloží do `/data/owut_pending_mail.json` a zkouší se znovu po 5 minutách

INSTALACE UPDATE
Tento ZIP nahraj do stejného GitHub repozitáře, kde už máš v3.6.11.
Ponech starší soubory `v369_extra.py`, `v369_patch.py` a `static/v369.js`; nový Dockerfile je používá.
Volume na iHostu ponech `mesh-controller-data:/data` a síť `host`.


v3.7.1:
- Gmail nastaveni obsahuje samostatne pole "Odeslat report na".
- Prijemce neni napevno; adresu lze kdykoliv zmenit ve webovem rozhrani.
- Nastaveni prijemce se uklada do /data/owut_settings.json, takze prezije aktualizaci kontejneru pri zachovani volume mesh-controller-data:/data.

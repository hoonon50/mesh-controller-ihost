# Troubleshooting v7.0.2

## Web se neotevře

Ověřte kontejner:

```sh
docker ps -a
docker logs --tail 200 <container>
```

Controller očekává host network a port 8088.

```text
http://IP_IHOST:8088
```

## Po update zmizelo nastavení

Nejdřív ověřte, zda nový kontejner používá stejné persistentní volume:

```text
mesh-controller-data:/data
```

Pokud byl vytvořen nový prázdný volume, původní data nemusí být připojená. Starý volume nemažte, dokud není situace ověřena.

## Router je OFFLINE v UI

Zkontrolujte:

- ping z iHostu,
- SSH port,
- uživatele/heslo v `/data/config.json`,
- zda router nezměnil IP,
- zda Controller není během reboot/sysupgrade čekací fáze.

## V logu OpenWrt je mnoho krátkých Dropbear session

v7.0.0 snížila běžné SSH zatížení. Normální jsou krátké session při live monitoringu, inspekci nebo servisní operaci. Desítky session za minutu na jednom routeru bez aktivní operace nejsou očekávaný běžný stav v7.0.x.

Ověřte, že skutečně běží nový image a header ukazuje v7.0.2.

## `Error reading: Connection reset by peer` v Dropbear

U krátkých Paramiko session může router logovat reset při ukončení spojení. Samotný jednotlivý reset nemusí znamenat poruchu routeru. Důležitá je četnost, dopad na funkci a případné autentizační chyby.

## LAN blokace se po rebootu routeru vrátila

To je očekávané. Persistentní blokovaný stav se po live detekci portu UP jednorázově znovu aplikuje.

## Nextcloud TEST selže HTTP 401

Obvykle jde o autentizaci:

- zkontrolujte uživatelské jméno,
- použijte správné heslo/App Password,
- zkontrolujte URL serveru,
- pokud je 2FA, preferujte App Password.

## Nextcloud TEST selže kvůli TLS

Image používá systémové CA certifikáty. U interního Nextcloudu se self-signed certifikátem nebude standardní ověření důvěry fungovat bez instalace důvěryhodné CA do prostředí. Nepotlačujte TLS validaci naslepo u produkčního backupu.

## Automatický OWUT se nespustil

Ve v7.0.2 musí na stejném scheduler triggeru nejprve projít Controller/Nextcloud backup. Zkontrolujte HTML report a `/data/controller_backup_status.json`.

Typická bezpečná příčina:

```text
NEXTCLOUD BACKUP: CHYBA
AUTOMATICKÝ OWUT: neproveden
```

## Retence nechala více než 10 souborů

Retence rozpoznává Controller backupy podle názvu:

```text
mesh-controller-backup_v*_YYYYMMDD-HHMMSS.tar.gz
```

Jiné ručně uložené soubory se nemusí počítat. Pokud upload prošel, ale DELETE/PROPFIND selhal, nová záloha zůstává platná a retenční problém je warning.

## Import backupu odmítne soubor

Import kontroluje formát, manifest, SHA-256, velikost a bezpečné relativní cesty. Nepřepisujte manifest ručně. Zkuste předchozí známou platnou zálohu.

## WAN historie nesedí

Ověřte `/data/wan_usage.json`. Backup před archivací volá flush, ale po kompletní ztrátě `/data` lze obnovit pouze stav zachycený v posledním externím backupu.

## ROUTER po OWUT nabootoval interně místo USB Extroot

Neformátujte USB disk. Nejprve:

```sh
df -hT / /overlay
block info
logread | grep -iE 'extroot|mount_root|block:|sda1|overlay' | tail -n 100
```

Pokud USB `/dev/sda1` existuje a data jsou čitelná, může jít pouze o boot-critical fstab problém. Recovery logika projektu je navržena tak, aby opravovala interní extroot konfiguraci bez destrukce USB dat.

## Po Docker build se zobrazuje jiná verze než ve zdrojovém `.py`

To může být očekávané. Projekt používá build-time patch chain. Posuzujte výsledný image po aplikaci všech patchů v `Dockerfile`, ne pouze základní nepřepatchovaný modul.

## Co přiložit při diagnostice

U Controller problému:

```sh
docker ps -a
docker logs --tail 300 <container>
```

U OpenWrt uzlu:

```sh
date
uptime
logread | tail -n 200
df -hT
```

U Extroot problému navíc `block info` a extroot/mount logy.
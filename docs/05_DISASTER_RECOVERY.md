# Disaster recovery – obnova Controlleru po havárii iHostu / SD karty

Tento postup řeší ztrátu Docker storage nebo SD karty iHostu. Základní předpoklad je, že máte ruční Controller backup z PC nebo automatický Controller backup uložený na Nextcloudu.

## Co potřebujete

- funkční SONOFF iHost s Dockerem,
- image OpenWRT MESH CONTROLLER PRO stejné nebo kompatibilní verze,
- přístup do webového UI Controlleru,
- soubor `mesh-controller-backup_v*.tar.gz`,
- síťovou dostupnost OpenWrt routerů.

## Varianta A – obnova z ručního backupu v PC

1. Na nové SD kartě / novém Docker prostředí spusťte Controller.
2. Připojte persistentní volume jako `/data`.
3. Otevřete web `http://IP_IHOST:8088`.
4. V sekci ZÁLOHA CONTROLLERU zvolte `IMPORTOVAT Z PC`.
5. Vyberte poslední platný `mesh-controller-backup_*.tar.gz`.
6. Controller ověří manifest a SHA-256.
7. Po úspěšné validaci připraví restore staging a restartuje se.
8. Při dalším startu aplikuje persistentní konfiguraci.
9. Ověřte routery, WAN historii, OWUT plán, LAN stavy a Nextcloud nastavení.

## Varianta B – backup je pouze na Nextcloudu

Nová čistá instance ještě nemusí znát Nextcloud přihlašovací údaje. Proto je nejjednodušší:

1. stáhnout poslední archiv z Nextcloudu do PC,
2. pokračovat podle Varianta A.

Automatický Nextcloud adresář je standardně:

```text
/OpenWRT-MESH-CONTROLLER
```

pokud jste jej v UI nezměnili.

## Co se obnoví

Controller backup je určen pro aplikační konfiguraci a historii, například:

- `/data/config.json`,
- WAN statistiky a měsíční historii,
- OWUT/Gmail nastavení,
- LAN persistentní stav,
- Nextcloud nastavení,
- další persistentní Controller soubory zahrnuté manifestem.

## Co se neobnoví z Controller backupu

Samostatné routerové backupy v:

```text
/data/backups
```

jsou z disaster-recovery Controller archivu záměrně vyloučené.

Pokud je chcete chránit proti ztrátě SD karty, je potřeba je zálohovat samostatně mimo iHost.

## Po obnově zkontrolujte

```text
1. UI se načte a ukazuje správnou verzi.
2. ROUTER/MESH1–4 jsou dosažitelné.
3. SSH autentizace funguje.
4. WAN historie obsahuje starší měsíce.
5. Automatický OWUT má správné dny/čas.
6. Nextcloud TEST PŘIPOJENÍ projde.
7. LAN block/protection stav odpovídá očekávání.
8. HASSIO/iHost chráněné porty nejsou zablokované.
```

## Když je Controller po importu nedostupný

Nejdřív ověřte Docker:

```sh
docker ps -a
docker logs --tail 200 <container>
```

Pokud používáte Compose:

```sh
docker compose ps
docker compose logs --tail=200
```

Zkontrolujte, že kontejner má host network a `/data` volume.

## Když backup nelze importovat

Typické důvody:

- neplatný tar.gz,
- chybějící `manifest.json`,
- nesouhlas SHA-256,
- archiv je z jiné aplikace,
- nebezpečná cesta v archivu,
- překročený limit importu.

V takovém případě archiv ručně neupravujte, pokud máte starší platnou kopii. Použijte předchozí backup.

## Doporučená strategie

- nechat automatický Nextcloud backup při každém automatickém OWUT,
- Nextcloud automaticky udržuje posledních 10 Controller backupů,
- občas ručně stáhnout Controller backup i do PC,
- samostatně chránit `/data/backups` s routerovými OpenWrt zálohami,
- nikdy nespoléhat jen na stejnou SD kartu, na které běží Controller.
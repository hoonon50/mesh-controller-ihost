# Persistentní data, Controller backup a Nextcloud

## `/data`

Docker volume je připojený do kontejneru jako:

```text
/data
```

Při běžném update image se tento volume zachovává.

Známé persistentní soubory používané v projektu zahrnují například:

```text
/data/config.json
/data/wan_usage.json
/data/mesh_operation.json
/data/mesh_scheduler_v500.json
/data/owut_settings.json
/data/lan_port_state.json
/data/controller_backup_settings.json
/data/controller_backup_status.json
/data/backups/
```

Přesný seznam může záviset na tom, které funkce už byly v konkrétní instalaci použity.

## Dva rozdílné typy zálohy

### 1. Záloha OpenWrt routerů

Je uložena v:

```text
/data/backups/
```

Obsahuje routerové sysupgrade backupy a je spravována samostatnou funkcí Controlleru.

### 2. Disaster-recovery backup Controlleru

Od v7.0.1 lze ručně stáhnout archiv Controlleru do PC a později jej importovat.

Archiv:

- je `tar.gz`,
- obsahuje `manifest.json`,
- obsahuje SHA-256 pro jednotlivé soubory,
- validuje strukturu a cesty,
- před exportem flushne WAN statistiky,
- po importu připraví obnovu a restartuje Controller.

## Co se do Controller backupu zahrnuje

Zahrnují se persistentní soubory samotného Controlleru, tedy konfigurace a historie potřebná k návratu aplikačního stavu.

Důležitý příklad:

```text
/data/wan_usage.json
```

Obsahuje měsíční historii RX/TX a je součástí Controller backupu.

## Co se záměrně vynechává

`/data/backups` se vynechává, protože jde o samostatné zálohy OpenWrt routerů.

Dále se vynechávají runtime/rozpracované stavy, které se nemají po disaster recovery vracet jako nedokončená operace, například aktuální operation state, runtime scheduler state, pending mail nebo dočasný restore staging.

## Ruční export do PC

Ve webu použijte:

```text
STÁHNOUT DO PC
```

Před vytvořením archivu se provede flush WAN statistik. Výsledný soubor má název podobný:

```text
mesh-controller-backup_v7.0.2_YYYYMMDD-HHMMSS.tar.gz
```

## Ruční import z PC

Použijte:

```text
IMPORTOVAT Z PC
```

Import:

1. ověří archiv a manifest,
2. ověří SHA-256,
3. připraví bezpečný restore staging,
4. vytvoří marker pending restore,
5. restartuje proces,
6. při novém startu aplikuje obnovené persistentní soubory ještě před načtením ostatního runtime stavu.

Router backupy v `/data/backups` se importem Controlleru nemění.

## Nextcloud nastavení

Ve webovém rozhraní lze uložit:

```text
Server / IP / hostname / URL
Uživatel
Heslo nebo App Password
Cílový adresář
```

Výchozí adresář:

```text
/OpenWRT-MESH-CONTROLLER
```

Pro přenos se používá Nextcloud WebDAV:

```text
/remote.php/dav/files/<uživatel>/...
```

Doporučen je Nextcloud App Password místo hlavního hesla účtu.

## Automatický backup ve v7.0.2

v7.0.2 ruší dřívější T−10 minut logiku. Automatický backup nemá vlastní čas ani vlastní dny.

Použije se přesně trigger automatického OWUT:

```text
NAPLÁNOVANÝ ČAS OWUT
        │
        ├─ flush WAN
        ├─ vytvoření Controller backupu
        ├─ validace
        ├─ upload na Nextcloud
        ├─ ověření souboru
        └─ pokud OK → pokračuje OWUT
```

Pokud nová Nextcloud záloha není potvrzená jako úspěšná, automatický OWUT nemá pokračovat do sysupgrade.

## Retence 10 záloh

Po úspěšném uploadu provede Controller WebDAV `PROPFIND` cílového adresáře. Rozpoznává soubory ve formátu:

```text
mesh-controller-backup_v*_YYYYMMDD-HHMMSS.tar.gz
```

Seřadí je od nejnovějšího a ponechá nejvýše:

```text
10
```

Starší odstraní přes WebDAV `DELETE`.

Pokud selže pouze retence, ale nový soubor už byl úspěšně nahrán a ověřen, nová pojistka je platná. Retenční chyba je warning a sama o sobě nemá rušit následný OWUT.

## Bezpečnost zálohy

Controller backup může obsahovat citlivá nastavení, včetně SSH/Nextcloud údajů. Archiv proto:

- neukládejte veřejně,
- neposílejte nešifrovaně cizím osobám,
- používejte zabezpečený Nextcloud,
- omezte přístup k účtu a cílové složce.

## Doporučený disaster-recovery režim

Mějte dvě nezávislé kopie:

1. automatické zálohy na Nextcloudu,
2. občasný ruční export do PC nebo na jiný fyzický disk.

Tím není obnova závislá pouze na SD kartě iHostu ani pouze na jednom serveru.
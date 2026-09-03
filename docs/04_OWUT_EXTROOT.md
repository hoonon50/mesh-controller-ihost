# OWUT, pořadí aktualizace a ROUTER Extroot

## Scheduler

Od v6.3.9 je jediným vlastníkem automatického OWUT plánování `PersistentMeshOperationManager`.

Legacy `_scheduler_loop()` v `owut_manager.py` je build patchem hard-disabled a jeho starý scheduler thread se nemá spouštět. Kompatibilní API může zůstat dostupné, ale automatická cesta má delegovat na persistentní manager.

Tento bod je zásadní: dvě paralelní automatické OWUT cesty by mohly použít rozdílný postup při ROUTER sysupgrade/Extroot recovery.

## OWUT pořadí uzlů

Automatický OWUT/sysupgrade používá:

```text
MESH2 → MESH3 → MESH4 → MESH1 → ROUTER
```

ROUTER je poslední, protože ovlivňuje centrální LAN/DHCP/gateway a jeho update může přerušit konektivitu.

## Běžný reboot

Běžná reboot operace má záměrně jiné pořadí:

```text
MESH2 → MESH3 → MESH4 → ROUTER → MESH1
```

## v7.0.2 a Controller backup před OWUT

Automatický backup se spouští stejným scheduler triggerem jako automatický OWUT. Neexistuje vlastní T−10 plán.

Na začátku plánované OWUT operace:

1. flush WAN statistik,
2. vytvoření Controller backupu,
3. validace archivu,
4. upload na Nextcloud,
5. ověření uploadu,
6. při úspěchu pokračuje běžný OWUT flow.

Při chybě nové Nextcloud zálohy se automatický OWUT bezpečně ukončí před sysupgrade.

## ROUTER s USB Extroot

Projekt obsahuje speciální recovery logiku pro ROUTER, který používá USB Extroot.

Historicky řešený stav po sysupgrade:

```text
ROUTER nabootuje z interního overlaye místo USB /overlay
```

To samo o sobě neznamená ztrátu dat na USB. Proto recovery nesmí zkratkovitě formátovat nebo znovu vytvářet disk.

## Bezpečnostní zásady Extroot recovery

Patche v řadě v6.3.5–v6.3.9 staví na těchto zásadách:

- před update se pracuje s živým USB UUID,
- USB Extroot se neformátuje,
- USB se nereparticionuje,
- USB overlay se nemaže,
- na USB se nekopíruje nový čistý overlay,
- při interním bootu se opravuje pouze interní boot-critical `fstab.extroot`, pokud je to potřeba,
- po opravě následuje další reboot a ověření,
- no-update větev nemá dělat zbytečný reboot ani zápis do Extroot konfigurace.

## Důležitá vlastnost OpenWrt Extroot

Po úspěšném přepnutí na USB může viditelný `/etc/config/fstab` z USB overlaye vypadat jinak než boot-critical konfigurace na skrytém interním rootfs_data. Proto samotná absence extroot mount sekce ve viditelném fstab není důkaz, že je aktivní Extroot špatně nastaven.

Rozhodující runtime kontrola je skutečný mount stav, například:

```sh
df -hT / /overlay
block info
```

Očekávaný aktivní Extroot typicky ukazuje `/dev/sda1` jako `/overlay` a root přes `overlayfs:/overlay`.

## Bezpečná diagnostika po problému

Neprovádět `mkfs`, repartici ani kopii overlaye. Nejdřív zjistit:

```sh
df -hT / /overlay
block info
logread | grep -iE 'extroot|mount_root|block:|sda1|overlay' | tail -n 100
```

A ověřit potřebné balíčky:

```sh
for p in block-mount e2fsprogs kmod-fs-ext4 kmod-usb-storage kmod-usb-storage-uas; do
  apk info -e "$p" >/dev/null 2>&1 && echo "$p OK" || echo "$p MISSING"
done
```

OpenWrt 25.12 používá `apk` místo historického `opkg`.

## Co nedělat při prvním neúspěšném bootu

Dokud není prokázané poškození USB filesystemu:

- neformátovat disk,
- nevytvářet novou partition table,
- nemazat `/dev/sda1`,
- nekopírovat nový overlay přes původní data,
- neměnit UUID naslepo.

Controller recovery je navržen konzervativně právě proto, aby původní USB data přežila i situaci, kdy OpenWrt dočasně nabootuje interně.
# OpenWRT MESH CONTROLLER PRO v7.0.2

SONOFF iHost · Docker · OpenWrt MESH controller

Tento archiv je dokumentační snapshot projektu **v7.0.2** vycházející z produkčního commitu:

`e3fe1272b7f48e9fa961d57d5f95ac58c52068eb`

Cílová platforma Docker image je **linux/arm/v7**. Webové rozhraní běží standardně na portu **8088**, kontejner používá `network_mode: host` a persistentní data jsou v Docker volume připojeném jako `/data`.

## Co Controller umí

- sledování pěti OpenWrt uzlů: ROUTER + MESH1 až MESH4,
- živou MESH topologii, RSSI/bitrate a klienty,
- Wi‑Fi a LAN inspekci,
- runtime blokování LAN portů s ochranou iHost/HASSIO,
- WAN download/upload statistiky a měsíční historii,
- zálohy konfigurace OpenWrt routerů,
- persistentní reboot/OWUT operace,
- automatický OWUT s bezpečnostní logikou pro ROUTER s USB Extroot,
- HTML e‑mailový report po automatické aktualizaci,
- ruční export/import zálohy samotného Controlleru,
- automatickou zálohu Controlleru na Nextcloud přes WebDAV při stejném plánovaném triggeru jako automatický OWUT,
- retenci posledních 10 automatických Controller backupů na Nextcloudu.

## Dokumentace

1. [Kompletní provozní příručka](docs/01_KOMPLETNI_PRIRUCKA.md)
2. [Architektura a moduly](docs/02_ARCHITEKTURA.md)
3. [Persistentní data a zálohy](docs/03_DATA_ZALOHY_NEXTCLOUD.md)
4. [OWUT, pořadí aktualizace a Extroot](docs/04_OWUT_EXTROOT.md)
5. [Disaster recovery / obnova po havárii](docs/05_DISASTER_RECOVERY.md)
6. [GitHub, Docker build a nasazení](docs/06_GITHUB_DOCKER_BUILD.md)
7. [Troubleshooting](docs/07_TROUBLESHOOTING.md)
8. [Manifest projektu v7.0.2](PROJECT_MANIFEST.md)

## Rychlé spuštění

### Varianta A – Docker Compose

```bash
docker compose build
docker compose up -d
```

Potom otevřete:

```text
http://IP_IHOST:8088
```

### Varianta B – image z GHCR

Projekt publikuje ARMv7 image do:

```text
ghcr.io/hoonon50/mesh-controller-ihost
```

Při ručním nasazení zachovejte:

- Network: `host`
- Port aplikace: `8088`
- Persistentní mount: `mesh-controller-data:/data`
- Restart policy: `unless-stopped`

## Důležité: /data nemažte

Při aktualizaci Controlleru se má zachovat stávající Docker volume `/data`. Obsahuje mimo jiné konfiguraci, WAN historii, OWUT nastavení, LAN stav a nastavení Nextcloudu. Samostatné zálohy OpenWrt routerů jsou v `/data/backups`.

## Bezpečnost

`/data/config.json` může obsahovat SSH přihlašovací údaje k routerům. Záloha Controlleru proto může být citlivý soubor. Používejte silné SSH heslo nebo vhodný klíč a pro Nextcloud je vhodný App Password.

## Poznámka ke snapshotu v7.0.2

Projekt používá historicky vrstvené build-time patch skripty. `Dockerfile` aplikuje patche postupně až po `v702_controller_backup_sync_patch.py`. Některé zdrojové soubory nebo starší README proto mohou před aplikací patchů obsahovat starší číslo verze nebo starší popis intervalu. Výsledný Docker build je určen pořadím patchů v `Dockerfile`.

V produkčním snapshotu v7.0.2 jsou stále některé pomocné image tagy v `.github/workflows/build-ihost.yml` a `docker-compose.yml` pojmenované `7.0.1`. Dokumentace tuto skutečnost nezakrývá; jde o stav zdrojového snapshotu. Tag `latest` je pro produkční nasazení rozhodující.

## Licence

Snapshot repozitáře neobsahuje samostatný soubor `LICENSE`. Před veřejnou redistribucí projektu mimo vlastní repozitář je vhodné licenci explicitně zvolit a přidat.
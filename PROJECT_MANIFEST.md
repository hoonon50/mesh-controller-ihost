# PROJECT MANIFEST – OpenWRT MESH CONTROLLER PRO v7.0.2

## Identita snapshotu

- Repozitář: `hoonon50/mesh-controller-ihost`
- Produkční base commit: `e3fe1272b7f48e9fa961d57d5f95ac58c52068eb`
- Produkční base tree: `8f08d0b11e62f97616640e62057e12aafb17f87d`
- Dokumentační/package větev: `package/v7.0.2-complete-docs`
- Cílová Docker architektura: `linux/arm/v7`
- Web port: `8088`
- Persistentní mount: `/data`
- Docker network mode: `host`

## Obsah balíku

ZIP obsahuje celý zdrojový strom projektu v7.0.2 a navíc dokumentaci vytvořenou pro tento archiv.

Hlavní skupiny:

```text
.github/workflows/        GitHub Actions
static/                   JavaScript/CSS frontend moduly
templates/                Jinja2 HTML
docs/                     kompletní dokumentace
*.py                      backend a build-time patch skripty
Dockerfile                produkční build
/docker-compose.yml       lokální Compose nasazení
config.example.json       bezpečný příklad konfigurace
README*.txt / README.md   release a provozní informace
```

## Hlavní programové moduly

```text
app.py
mesh_core.py
mesh_operation_manager.py
owut_manager.py
live_topology_v503.py
wifi_ap_policy_v600.py
lan_port_control_v620.py
lan_port_inspector_v630.py
topology_inspector_v631.py
client_ip_resolver_v632.py
ihhost_temperature_v636.py
wan_usage.py
controller_backup_v701.py
```

Poznámka: skutečný název souboru s teplotou je `ihost_temperature_v636.py`; výše uvedený seznam slouží jako orientační mapa modulů.

## Build-time patch chain

Projekt obsahuje historické patche od řady v3.x až po v7.0.2. Rozhodující poslední vrstvy jsou:

```text
v638_extroot_double_reboot_patch.py
v639_single_owut_owner_patch.py
v700_ssh_load_patch.py
v701_controller_backup_patch.py
v701_report_fix_patch.py
v702_controller_backup_sync_patch.py
```

Po aplikaci patchů Dockerfile provádí Python compile a Jinja template kontrolu.

## Dokumentační soubory přidané pouze do package snapshotu

```text
README.md
README_v7.0.2.txt
PROJECT_MANIFEST.md
docs/01_KOMPLETNI_PRIRUCKA.md
docs/02_ARCHITEKTURA.md
docs/03_DATA_ZALOHY_NEXTCLOUD.md
docs/04_OWUT_EXTROOT.md
docs/05_DISASTER_RECOVERY.md
docs/06_GITHUB_DOCKER_BUILD.md
docs/07_TROUBLESHOOTING.md
```

Tyto soubory nemění runtime programu.

## Integrita ZIPu

Packaging workflow před vytvořením archivu vytvoří:

```text
SOURCE_COMMIT.txt
SOURCE_FILE_LIST.txt
SHA256SUMS.txt
```

`SHA256SUMS.txt` obsahuje kontrolní součty souborů uvnitř balíku před samotným zazipováním.

## Citlivá data

Zdrojový balík nemá obsahovat runtime `/data`. Před vložením do veřejného GitHub repozitáře ověřte, že jste do stromu ručně nepřidali:

- reálná SSH hesla,
- Nextcloud App Password,
- Gmail heslo/token,
- exporty `/data/config.json`,
- osobní backupy routerů.

`config.example.json` používá zástupnou hodnotu `CHANGE_ME`.

## Licence

Produkční snapshot neobsahuje samostatný `LICENSE`. Dokumentační balík licenci nepřidává ani nepředpokládá. Při veřejné redistribuci mimo původní repozitář je vhodné licenční podmínky explicitně doplnit.
# Architektura projektu v7.0.2

## Přehled

Aplikace je Flask/Gunicorn webová služba pro SONOFF iHost. Komunikace s OpenWrt uzly probíhá přes SSH/Paramiko. Persistentní stav je oddělen od image a ukládá se do `/data`.

## Hlavní backend soubory

| Soubor | Úloha |
|---|---|
| `app.py` | start Flask aplikace a registrace modulů |
| `mesh_core.py` | základní konfigurace, SSH klient, snapshoty a obecné operace |
| `mesh_operation_manager.py` | persistentní reboot/OWUT operace, scheduler, HTML report |
| `owut_manager.py` | historická OWUT implementace; automatický legacy scheduler je v novějších verzích hard-disabled |
| `live_topology_v503.py` | live topologie, klienti, mesh linky a část fyzických LAN stavů |
| `lan_port_control_v620.py` | runtime blokování/povolování LAN portů |
| `lan_port_inspector_v630.py` | detail klienta na LAN portu |
| `topology_inspector_v631.py` | inspekce klientů podle MESH uzlu |
| `client_ip_resolver_v632.py` | aktivní MAC→IPv4 doplnění přes MAIN router |
| `wifi_ap_policy_v600.py` | AP inactivity policy |
| `wan_usage.py` | WAN RX/TX statistiky a historie |
| `ihost_temperature_v636.py` | čtení teploty iHostu pro UI/report |
| `controller_backup_v701.py` | základ Controller backup/export/import/Nextcloud; výslednou v7.0.2 logiku doplňuje build patch |

## Frontend

`templates/index.html` je hlavní stránka. CSS/JS jsou rozdělené podle funkcí v adresáři `static/`.

Důležité assety:

- `app.js`, `style.css` – základ UI,
- `v503_live_topology.*` – topologie,
- `v620_lan_port_control.*` – LAN control,
- `v630_lan_port_inspector.*` – LAN detail,
- `v631_topology_inspector.*` – klienti uzlu,
- `wan_usage.*`, `wan_history.*` – WAN statistiky,
- `v500_operation.*` – průběh persistentní operace,
- `v701_controller_backup.*` – Controller backup a Nextcloud nastavení.

## Build-time patch architektura

Projekt je historicky evoluční a nepoužívá pouze jeden čistý zdrojový strom. `Dockerfile` po `COPY . .` spouští patch skripty v přesném pořadí. Výsledný runtime je tedy kombinací základních souborů a všech aplikovaných patchů.

Aktuální konec řetězce v7.0.2:

```text
...
v638_extroot_double_reboot_patch.py
v639_single_owut_owner_patch.py
v700_ssh_load_patch.py
v701_controller_backup_patch.py
v701_report_fix_patch.py
v702_controller_backup_sync_patch.py
```

Potom probíhá `python3 -m py_compile` hlavních modulů a validace Jinja2 šablony.

## Background komponenty

Projekt obsahuje několik periodických částí. Důležitým návrhovým pravidlem je jediný Gunicorn worker, aby se scheduler nebo background manager nespustil vícekrát.

Ve v7.0.0 byl snížen SSH load. Ve v7.0.2 je navíc samostatný Controller backup scheduler vypnutý; automatický backup se synchronně spouští stejným scheduler triggerem jako automatický OWUT.

## Síťová komunikace

- Web: HTTP na portu 8088 v host network.
- Routery: SSH/Paramiko na adresy z `/data/config.json`.
- Nextcloud: HTTP/HTTPS WebDAV z iHost kontejneru.
- Gmail/report: používá existující persistentní OWUT/Gmail nastavení projektu.

## Persistentní vs. image data

Image obsahuje program. `/data` obsahuje stav. Aktualizace image proto nesmí automaticky smazat volume.

To je zásadní pro:

- SSH konfiguraci,
- WAN historii,
- scheduler/OWUT nastavení,
- LAN block state,
- Controller backup/Nextcloud nastavení,
- router backupy v `/data/backups`.
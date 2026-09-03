# Kompletní provozní příručka – OpenWRT MESH CONTROLLER PRO v7.0.2

## 1. Účel projektu

Controller je webová aplikace v Python/Flask běžící v Dockeru na SONOFF iHost. Přes SSH/Paramiko komunikuje s pěti OpenWrt uzly a sjednocuje monitoring, údržbu, zálohy, reboot a OWUT operace do jednoho webového rozhraní.

Výchozí topologie v `config.example.json`:

| Název | IP |
|---|---|
| ROUTER | 192.168.30.1 |
| MESH1 | 192.168.30.2 |
| MESH2 | 192.168.30.3 |
| MESH3 | 192.168.30.4 |
| MESH4 | 192.168.30.5 |

Výchozí web Controlleru:

```text
http://IP_IHOST:8088
```

## 2. Docker parametry

Projekt používá:

- cílovou architekturu `linux/arm/v7`,
- `network_mode: host`,
- persistentní volume `mesh-controller-data:/data`,
- restart policy `unless-stopped`,
- jeden Gunicorn worker a více vláken; jediný worker je důležitý kvůli schedulerům a background managerům.

### Docker Compose

```bash
docker compose build
docker compose up -d
```

### Zásada při aktualizaci

Nikdy nemažte volume `mesh-controller-data`, pokud nechcete záměrně začít s čistou konfigurací. Nový image se má spustit proti stávajícímu `/data`.

## 3. Konfigurace routerů a SSH

Ukázka je v `config.example.json`.

```json
{
  "routers": [
    {"ip": "192.168.30.1", "name": "ROUTER", "backup_name": "ROUTER.tar.gz"},
    {"ip": "192.168.30.2", "name": "MESH1", "backup_name": "MESH1.tar.gz"},
    {"ip": "192.168.30.3", "name": "MESH2", "backup_name": "MESH2.tar.gz"},
    {"ip": "192.168.30.4", "name": "MESH3", "backup_name": "MESH3.tar.gz"},
    {"ip": "192.168.30.5", "name": "MESH4", "backup_name": "MESH4.tar.gz"}
  ],
  "ssh": {
    "user": "root",
    "password": "CHANGE_ME",
    "key_file": "",
    "timeout": 5
  }
}
```

Runtime konfigurace je persistentně v `/data/config.json`.

Doporučení:

- změnit výchozí/slabá SSH hesla,
- nevystavovat SSH OpenWrt routerů do internetu,
- chránit export Controlleru, protože může obsahovat přihlašovací údaje.

## 4. Live monitoring

Controller zobrazuje stav MESH uzlů a klientů. Ve v7.0.0 byl záměrně snížen počet SSH relací:

- Live Topology backend: 15 s,
- frontend Live Topology: 15 s,
- legacy snapshot refresh: minimálně 60 s,
- LAN protection scan: 60 s,
- při již zablokovaném DOWN portu se neposílá slepě další `ip link set ... down`,
- při nedostupných live datech je reassert fallback omezen přibližně na 300 s,
- chyba opakované LAN akce se nereaguje rychleji než přibližně po 60 s.

Krátkodobě může počet SSH session vzrůst při otevření inspektoru, ručním refreshi, startu kontejneru, obnově blokace nebo údržbové operaci.

## 5. Wi‑Fi klienti a topologie

Projekt kombinuje data z hostapd/UBUS, `iw`, bridge FDB, ARP/neighbour a DHCP zdrojů. Historické vrstvy projektu zpřísňovaly rozlišení živého klienta od starého DHCP/ARP záznamu.

V UI jsou oddělené informace pro 2.4 GHz, 5 GHz, LAN a topologii mezi uzly. Pro některé klienty existuje aktivní MAC→IPv4 resolver přes MAIN router.

## 6. LAN porty

Controller umí runtime blokaci LAN portu bez UCI změny. Stav je persistentní, aby se po rebootu routeru mohl znovu aplikovat.

Důležité bezpečnostní chování:

- iHost a HASSIO porty jsou chráněné před nechtěnou blokací,
- v7.0.0 se blokace již slepě neopakuje každých 5 s,
- když live stav ukáže, že blokovaný port je po rebootu znovu UP, Controller jej jednorázově znovu zablokuje.

## 7. WAN statistiky

WAN přenosy jsou ukládány persistentně v:

```text
/data/wan_usage.json
```

Soubor obsahuje aktuální stav i měsíční/roční historii RX/TX. Před vytvořením Controller backupu se v7.0.1+ provede flush statistik, aby archiv zachytil co nejaktuálnější stav.

## 8. Zálohy OpenWrt routerů

Zálohy routerů jsou samostatná funkce Controlleru a ukládají se do:

```text
/data/backups
```

Názvy jsou typicky:

```text
ROUTER.tar.gz
MESH1.tar.gz
MESH2.tar.gz
MESH3.tar.gz
MESH4.tar.gz
```

Tyto soubory nejsou součástí disaster-recovery backupu samotného Controlleru.

## 9. Backup samotného Controlleru

Od v7.0.1 existuje:

- `STÁHNOUT DO PC`,
- `IMPORTOVAT Z PC`,
- tar.gz archiv s `manifest.json`,
- SHA-256 kontrola jednotlivých souborů,
- bezpečnostní kontrola cest při importu,
- restart Controlleru před aplikací připravené obnovy.

Do zálohy jsou zahrnuta persistentní data Controlleru, například konfigurace, WAN historie, OWUT/Gmail nastavení, LAN stavy a Nextcloud nastavení.

Záměrně se vynechává:

- `/data/backups`,
- rozpracovaný runtime operation state,
- runtime scheduler state,
- pending mail,
- dočasné restore soubory.

## 10. Nextcloud WebDAV

Ve webu lze nastavit:

- IP/hostname nebo URL Nextcloud serveru,
- uživatelské jméno,
- heslo/App Password,
- cílový adresář, výchozí `/OpenWRT-MESH-CONTROLLER`.

Ve v7.0.2 automatická záloha nemá vlastní scheduler. Použije přesně stejný plánovaný trigger jako automatický OWUT:

```text
čas OWUT
  ↓
Controller backup + WAN flush
  ↓
validace archivu
  ↓
WebDAV upload na Nextcloud
  ↓
ověření uploadu
  ↓
pokud OK → pokračuje OWUT
```

Pokud samotná nová záloha na Nextcloud selže, automatický OWUT nemá pokračovat.

Po úspěšném uploadu se přes WebDAV načte seznam Controller backupů a ponechá se nejvýše 10 nejnovějších automatických archivů. Pokud selže pouze úklid starých souborů, nová záloha zůstává platná a OWUT může pokračovat; problém retence je veden jako warning.

## 11. Automatický OWUT

Jediným vlastníkem automatického OWUT scheduleru je `PersistentMeshOperationManager`. Legacy scheduler v `owut_manager.py` byl od v6.3.9 hard-disabled, aby nemohly paralelně běžet dvě odlišné automatické cesty.

OWUT/sysupgrade pořadí:

```text
MESH2 → MESH3 → MESH4 → MESH1 → ROUTER
```

Běžný reboot má jiné pořadí:

```text
MESH2 → MESH3 → MESH4 → ROUTER → MESH1
```

## 12. ROUTER a USB Extroot

ROUTER může používat USB Extroot. Aktualizační logika v řadě v6.3.5–v6.3.9 chrání USB overlay před destruktivními zásahy.

Zásady:

- žádné format/wipe/repartition USB,
- recovery nemá kopírovat nový overlay na USB,
- před update se pracuje s živým UUID USB Extroot zařízení,
- po sysupgrade se počítá s reboot flow pro návrat Extrootu,
- pokud je po bootu router interní, fallback smí opravovat pouze interní `fstab.extroot` podle původního živého UUID.

Podrobnosti jsou v `docs/04_OWUT_EXTROOT.md`.

## 13. E-mailový report

Projekt používá existující HTML report automatického OWUT. Backup nepřidává samostatný e-mail.

Do závěrečného reportu se doplňuje stav například:

```text
CONTROLLER BACKUP: OK
NEXTCLOUD BACKUP: OK
SOUBOR: mesh-controller-backup_v7.0.2_YYYYMMDD-HHMMSS.tar.gz
```

Report má být odeslán až po dokončení automatické aktualizační operace nebo při jejím bezpečném ukončení s chybou.

## 14. Verze v7.0.2

v7.0.2 proti v7.0.1 mění pouze automatickou zálohu Controlleru:

- ruší T−10 minut,
- backup používá stejný trigger jako OWUT,
- po úspěšném backupu OWUT bezprostředně pokračuje,
- Nextcloud udržuje nejvýše 10 nejnovějších automatických Controller backupů,
- ruční export/import z PC zůstává,
- MESH/SSH/Extroot/LAN logika se proti v7.0.1 nemění.

## 15. Známé vlastnosti zdrojového snapshotu

Repozitář je historicky patchovaný. `Dockerfile` nejprve zkopíruje základní zdroje a potom aplikuje řadu `vXXX_*_patch.py`. Proto není správné posuzovat výsledný v7.0.2 image pouze podle jednoho nepřepatchovaného zdrojového souboru.

V přesném produkčním snapshotu commitu `e3fe1272...` jsou `docker-compose.yml` a produkční GHCR workflow stále pojmenované tagem `7.0.1`. Runtime patch v7.0.2 však upravuje výsledné aplikační metadata a logiku backupu. Dokumentační balík tuto skutečnost zachovává beze změny zdrojového programu.
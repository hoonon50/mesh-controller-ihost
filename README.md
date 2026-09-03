# OpenWRT MESH CONTROLLER PRO v7.0.2

Finální flattened produkční zdroj pro SONOFF iHost (`linux/arm/v7`).

Historické `*_patch.py` soubory už nejsou potřeba: všechny změny až po v7.0.2 jsou napevno aplikované v aktuálních zdrojových souborech.

- Web: `http://IP_IHOST:8088`
- Docker network: `host`
- Persistentní volume: `mesh-controller-data:/data`
- Image: `ghcr.io/hoonon50/mesh-controller-ihost:7.0.2`
- GitHub Actions z `main` publikuje `:latest` a `:7.0.2`

Persistentní `/data` nemažte. Obsahuje konfiguraci, WAN statistiky, OWUT nastavení, LAN stavy a Controller/Nextcloud nastavení.

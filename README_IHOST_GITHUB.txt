OpenWrt Mesh Controller PRO WEB v3.0 – iHost ARMv7

TATO VARIANTA NEVYZADUJE DOCKER NA DEBIANU.

Cíl:
- image: linux/arm/v7
- registry: GitHub Container Registry (ghcr.io)
- běh: přímo v SONOFF iHost Dockeru
- web: http://IP_IHOST:8088
- network: host
- volume: libovolný persistentní volume připojit do /data

Postup:
1. Na GitHubu vytvořit nový veřejný repository, např. mesh-controller-ihost.
2. Nahrát do něj OBSAH této složky (Dockerfile, app.py, mesh_core.py, templates, static a .github).
3. Otevřít záložku Actions. Workflow "Build iHost ARMv7 image" se spustí automaticky po nahrání do main.
4. Po úspěšném buildu vznikne image:
   ghcr.io/TVOJE_GITHUB_JMENO/mesh-controller-ihost:latest
5. Pokud Package není veřejný, v GitHub Packages změnit jeho visibility na Public.
6. V iHost Dockeru přidat image podle výše uvedeného názvu.
7. Network nastavit na host.
8. Vytvořit persistentní volume a připojit ho do /data.
9. Spustit kontejner.
10. Otevřít http://IP_IHOST:8088

Poznámka:
config.json vznikne při prvním startu v /data. Výchozí SSH hodnoty odpovídají původnímu programu; po prvním testu je doporučeno změnit heslo/SSH klíč.

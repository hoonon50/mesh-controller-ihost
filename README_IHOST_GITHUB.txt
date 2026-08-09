OpenWrt Mesh Controller PRO WEB v3.2 – iHost ARMv7

Aktualizace stávající instalace:
1. V GitHub repository mesh-controller-ihost nahrajte obsah aktualizačního ZIPu v3.2 a přepište stejnojmenné soubory.
2. GitHub Actions automaticky sestaví nový image:
   ghcr.io/TVOJE_GITHUB_JMENO/mesh-controller-ihost:latest
3. Počkejte na zelenou fajfku v Actions.
4. V iHostu ponechte stávající persistentní volume připojený jako /data.
5. Aktualizujte/pullněte image latest a kontejner znovu vytvořte/spusťte se sítí host.
6. Otevřete http://IP_IHOST:8088

Důležité:
- volume mesh-controller-data:/data nemažte
- SAFE MESH ani SSH terminál ve v3.2 nejsou
- v3.2 přidává živý progress panel pro delší operace
- existující config.json z v3.1 lze ponechat beze změny; případné terminal_pin/terminal_timeout se ignorují

OpenWRT MESH CONTROLLER PRO v7.0.1
===================================

Rozsah verze
------------
Tato verze mění pouze zálohu samotného Controlleru. Logika MESH, SSH polling,
LAN portů, Extrootu, pořadí routerů a OWUT/sysupgrade zůstává beze změny oproti v7.0.0.

Nová funkce: ZÁLOHA CONTROLLERU
-------------------------------
- ruční STÁHNOUT DO PC
- ruční IMPORTOVAT Z PC
- bezpečný archiv tar.gz s manifestem a SHA-256 kontrolou
- před vytvořením archivu se flushne aktuální WAN statistika
- součástí zálohy je /data/wan_usage.json včetně měsíční historie RX/TX
- součástí jsou persistentní nastavení Controlleru včetně OWUT/Gmail, LAN stavů
  a nastavení Nextcloudu
- /data/backups se záměrně NEZÁLOHUJE, protože obsahuje samostatné zálohy OpenWrt routerů
- rozpracovaná operace, runtime scheduler a pending mail se do disaster-recovery archivu neukládají

Nextcloud WebDAV
----------------
Uživatel si ve webu nastaví:
- IP / hostname / kompletní URL Nextcloud serveru
- uživatelské jméno
- heslo nebo doporučený Nextcloud App Password
- cílový adresář, výchozí /OpenWRT-MESH-CONTROLLER

Den ani čas Nextcloud zálohy nemá vlastní volbu.
Automatická Nextcloud záloha se vždy odvozuje od existujícího automatického OWUT:
- stejné dny jako OWUT
- přesně 10 minut před časem OWUT
- funguje i při čase OWUT krátce po půlnoci

Před automatickým OWUT
----------------------
1. T-10 min: flush WAN statistiky.
2. Vytvoření a ověření Controller backupu.
3. Upload přes Nextcloud WebDAV.
4. Ověření souboru na Nextcloudu.
5. T: automatický OWUT převezme výsledek backupu.
6. Bez potvrzené úspěšné Nextcloud zálohy se automatický OWUT nespustí.

E-mailový report
----------------
Nevzniká žádný nový samostatný e-mail v T-10 min.
Do stávajícího grafického HTML reportu automatického OWUT jsou pouze doplněny řádky:

CONTROLLER BACKUP: OK / CHYBA
NEXTCLOUD BACKUP: OK / CHYBA
SOUBOR: mesh-controller-backup_v7.0.1_YYYYMMDD-HHMMSS.tar.gz

Při úspěšné aktualizaci přijde tento údaj až ve stávajícím závěrečném reportu OWUT.
Pokud předaktualizační backup selže, automatický OWUT se bezpečně ukončí před sysupgrade
a původní OWUT failure report uvede důvod chyby backupu.

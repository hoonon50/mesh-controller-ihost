OpenWRT MESH CONTROLLER PRO v7.0.2
===================================

Rozsah verze
------------
Tato verze mění pouze automatickou zálohu samotného Controlleru oproti v7.0.1.
MESH, SSH polling, LAN porty, Extroot recovery, pořadí routerů a vlastní OWUT/sysupgrade
logika zůstávají funkčně beze změny.

AUTOMATICKÝ CONTROLLER/NEXTCLOUD BACKUP
--------------------------------------
- ruší se dřívější T-10 minut plánování
- automatický backup nemá vlastní scheduler
- backup se spouští přesně stejným plánovaným triggerem jako automatický OWUT
- nejdřív se flushnou WAN statistiky
- vytvoří se a ověří Controller backup
- uploadne se na Nextcloud přes WebDAV
- upload se ověří
- při úspěchu pokračuje automatický OWUT
- bez potvrzené nové Nextcloud zálohy se automatický OWUT bezpečně nespustí

NEXTCLOUD RETENCE
-----------------
- po úspěšném uploadu se načte seznam automatických Controller backupů
- ponechá se maximálně 10 nejnovějších archivů
- starší jsou odstraněny přes WebDAV DELETE
- retenční chyba po úspěšném uploadu neznehodnotí novou zálohu; je vedena jako warning

RUČNÍ BACKUP/RESTORE
--------------------
- STÁHNOUT DO PC zůstává beze změny
- IMPORTOVAT Z PC zůstává beze změny
- /data/wan_usage.json včetně měsíční historie je součástí Controller backupu
- /data/backups s OpenWrt router backupy je záměrně vyloučeno

E-MAILOVÝ REPORT
----------------
Nevzniká samostatný backup e-mail.
Výsledek Controller/Nextcloud backupu je součástí existujícího závěrečného HTML OWUT reportu.

VALIDACE
--------
v7.0.2 byla před merge validována ARMv7 Docker buildem, smoke startem kontejneru
a testem retence 12 -> 10 Controller backupů.

PRODUKČNÍ COMMIT
----------------
e3fe1272b7f48e9fa961d57d5f95ac58c52068eb

POZNÁMKA KE ZDROJŮM
-------------------
Projekt používá build-time patch řetězec. Finální v7.0.2 změny jsou aplikovány
skriptem v702_controller_backup_sync_patch.py v Dockerfile. Některé základní
soubory před aplikací patchů proto mohou obsahovat starší verzi.

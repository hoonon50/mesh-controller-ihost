OpenWRT MESH CONTROLLER PRO v6.3.6

SAFE SCHEDULED OWUT + IHOST TEMPERATURE
----------------------------------------
Tato verze navazuje na v6.3.5 a zpřísňuje automatickou/plánovanou OWUT aktualizaci.

Když není dostupný žádný update:
- proběhne pouze kontrola dostupnosti, OWUT preflight a read-only kontrola aktivního USB Extrootu
- nevytváří se zbytečná pre-upgrade záloha
- nespouští se owut upgrade/sysupgrade
- neprovádí se žádný reboot
- /overlay ani /etc/config/fstab se nemění
- log i Gmail report výslovně uvedou, že Extroot zůstal beze změny

Když update dostupný je:
- před sysupgrade se uloží živé UUID aktivního USB /overlay
- po prvním bootu na interním overlayi se nejdřív ověří nový OpenWrt release/revision
- ověří se příkazy uci, block, blkid a owut
- ověří se balíčky block-mount, kmod-fs-ext4, kmod-usb-storage a kmod-usb-storage-uas
- ověří se podpora ext4 a USB blokové zařízení /dev/sd* se stejným UUID a TYPE=ext4
- až potom se obnoví a ověří interní fstab.extroot
- teprve po úspěšném ověření se provede druhý reboot
- po druhém bootu se znovu ověří /overlay na USB a přesná shoda UUID
- při jakémkoli selhání před druhým rebootem se operace zastaví a ROUTER zůstane dostupný přes SSH na interním systému

MAIL REPORTY:
- OWUT reporty i Persistent Operation Manager používají jeden společný iHost CPU/SoC temperature reader
- čtou se pouze skutečné thermal_zone*/temp a hwmon temp*_input hodnoty
- při dočasném N/A se čtení krátce opakuje

Zůstává zachováno:
- v6.3.5 bezpečná obnova Extrootu
- v6.3.4 OWUT PID/log/heartbeat launcher
- pořadí MESH2 -> MESH3 -> MESH4 -> MESH1 -> ROUTER
- automatický Gmail report
- persistentní /data beze změny
- live LAN/topology/client funkce

Image tagy: latest, 6.3.6

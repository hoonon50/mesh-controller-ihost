OpenWRT MESH CONTROLLER PRO v6.3.5

EXTROOT SAFE RECOVERY
---------------------
Tato verze řeší selhání hlavního ROUTERu po OWUT sysupgrade, kdy po prvním bootu
zmizela interní konfigurace Extrootu a druhý reboot proto nemohl znovu připojit
USB /overlay.

Nové chování:
- před sysupgrade se ověří aktivní USB /overlay a živé UUID
- UUID se nehardcoduje
- po prvním bootu se zjistí skutečný typ aktivního overlaye
- pokud ROUTER běží z interního UBIFS/rootfs_data, Controller vytvoří a ověří
  fstab.extroot právě v tomto interním overlayi
- druhý reboot se provede až po úspěšném ověření UUID, target=/overlay,
  fstype=ext4 a enabled=1
- pokud USB s očekávaným UUID není dostupné nebo fstab nelze ověřit, druhý reboot
  se neprovede a ROUTER zůstane dostupný pro servis přes SSH
- po druhém bootu se kontroluje nejen /dev/sd* na /overlay, ale i přesná shoda UUID
- při chybě se přidá diagnostika fstab, block info a extroot/mount_root logu

Důvod:
Na funkčním zařízení může být po přepnutí na Extroot viditelné /etc/config/fstab
na USB bez sekce extroot. Rozhodující konfigurace pro PREINIT se nachází na
interním rootfs_data/UBIFS, které je při aktivním Extrootu překryté. Proto se
obnova musí dělat mezi prvním a druhým bootem, když je interní overlay skutečně
aktivní.

Zůstává zachováno:
- v6.3.4 spolehlivý OWUT launcher + PID/log/heartbeat
- pořadí MESH2 -> MESH3 -> MESH4 -> MESH1 -> ROUTER
- plné pre-upgrade zálohy všech routerů
- automatický Gmail report
- USB balíčky přidávané do ROUTER image přes OWUT --add
- live LAN/topology/client funkce
- /data persistence bez změny

Image tagy: latest, 6.3.5

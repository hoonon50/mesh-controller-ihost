OpenWRT MESH CONTROLLER PRO v6.3.8

Oprava automatického USB Extroot návratu po skutečném OWUT/sysupgrade ROUTERu .1.

PROBLÉM
-------
v6.3.6/v6.3.7 po prvním interním bootu prováděla vlastní přísný first-boot gate. Pokud neprošla kontrola příkazů/balíčků/ext4, Controller zrušil potřebný druhý reboot a ROUTER zůstal na interním /dev/ubi0_2. To odpovídá logu z 17.08.2026, kde sysupgrade proběhl, první interní boot byl dostupný, ale druhý reboot byl zrušen.

NOVÉ CHOVÁNÍ
------------
1. Před sysupgrade musí být aktivní USB Extroot a uloží se jeho živé UUID.
2. OWUT/sysupgrade proběhne stejně jako dosud.
3. První boot může být na interním overlay – to je považováno za očekávaný Extroot stav.
4. Po stabilním SSH se čeká 15 s a bez změny fstab se provede standardní druhý reboot.
5. Po druhém bootu se ověří USB /overlay a přesná shoda UUID.
6. Pokud je ROUTER stále na interním overlay, fallback vyhledá USB disk podle původního UUID, ověří ext4 a zapíše pouze interní fstab.extroot.
7. Následuje třetí reboot a finální ověření USB /overlay + stejného UUID.

BEZPEČNOST
----------
- žádný format
- žádný wipefs
- žádné repartition
- žádné mkfs
- žádné kopírování/reseed dat na USB overlay
- žádné hardcoded UUID ani /dev/sda1
- USB disk se identifikuje podle živého UUID uloženého před sysupgrade
- no-update OWUT stále neprovádí reboot ani zápis do Extrootu

Ostatní chování v6.3.7 zůstává beze změny.

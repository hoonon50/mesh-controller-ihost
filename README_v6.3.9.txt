OpenWRT MESH CONTROLLER PRO v6.3.9

OPRAVA DUPLICITNÍHO AUTOMATICKÉHO OWUT
--------------------------------------
Příčina opakovaného problému s Extrootem nebyla v /dev/sda1. USB disk a jeho data zůstaly v pořádku.

V kontejneru ale stále běžely dva automatické OWUT schedulery:
1. PersistentMeshOperationManager – nová správná cesta s v6.3.8 Extroot recovery.
2. Legacy scheduler v owut_manager.py – stará cesta s first-boot package gate.

Legacy scheduler mohl při automatické aktualizaci spustit _upgrade_worker z owut_manager.py. Po prvním bootu ROUTERu na interním /dev/ubi0_2 tato stará cesta provedla vlastní kontrolu a mohla zrušit potřebný druhý reboot. Výsledkem byl ROUTER ponechaný na interním overlay, i když /dev/sda1 a jeho ext4 data byly neporušené.

ZMĚNY v6.3.9
------------
- jediný automatický OWUT scheduler je PersistentMeshOperationManager
- legacy _scheduler_loop(controller) v owut_manager.py je hard-disabled
- thread name=owut-scheduler se již vůbec nevytváří
- /api/owut/upgrade už nespouští legacy _upgrade_worker; kvůli kompatibilitě deleguje na mesh_operation_v500
- nastavení automatického plánu v /data/owut_settings.json zůstává zachováno
- persistent scheduler dál používá stejný čas / daily-weekly / Gmail nastavení
- build obsahuje pojistky a skončí chybou, pokud by se legacy scheduler thread nebo legacy upgrade API znovu aktivovaly
- runtime zároveň ověřuje přítomnost v6.3.8 bezpečného Extroot flow

EXTROOT FLOW, KTERÝ ZŮSTÁVÁ AKTIVNÍ
-----------------------------------
- před sysupgrade se vyžaduje zdravý USB Extroot a uloží se živé UUID
- první interní boot po sysupgrade je očekávaný
- následuje standardní druhý reboot bez změny fstab
- po druhém bootu se ověří USB /overlay a přesná shoda UUID
- jen pokud zůstane interní overlay, fallback vyhledá původní USB podle UUID, ověří ext4, zapíše pouze interní fstab.extroot a provede další reboot
- žádný format / wipefs / mkfs / repartition / copy overlay dat

PO AKTUALIZACI CONTROLLERU
--------------------------
Kontejner v6.3.9 musí být restartovaný / znovu vytvořený, což standardní aktualizace Controlleru udělá. Tím zmizí starý již běžící legacy scheduler thread. Persistentní /data zůstává beze změny.

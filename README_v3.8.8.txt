OpenWRT MESH CONTROLLER PRO v3.8.8
=================================

Zmena pro iHost pripojeny LAN kabelem do MESH1 192.168.30.2:

NOVÉ PORADI OWUT / RESTART VSECH
1. MESH2  192.168.30.3
2. MESH3  192.168.30.4
3. MESH4  192.168.30.5
4. MESH1  192.168.30.2  <- iHost je pripojen zde, proto posledni satelit
5. ROUTER 192.168.30.1

BEZPECNOSTNI POJISTKA
- po MESH1 .2 se pred ROUTERem .1 znovu overi SSH dostupnost MESH1 .2
- potom se overi SSH dostupnost ROUTERu .1
- az kdyz jsou oba dostupne, spusti se OWUT na ROUTERu .1
- pokud se MESH1 nevrati, ROUTER .1 se neaktualizuje a operace skonci chybovym reportem

Zachovano z v3.8.7:
- planovane i rucni Gmail reporty
- HTML/TEXT report
- CPU teploty
- zalohy pred sysupgrade
- dvojity restart ROUTERu .1 pri skutecnem sysupgrade s USB Extroot
- kontrola USB overlay + UUID
- scheduler Kazdy den / Vybrany den
- zadny automaticky destruktivni setup USB overlay

OpenWRT MESH CONTROLLER PRO v7.0.0
===================================

Hlavní změna: výrazné omezení zbytečných SSH relací z iHost Controlleru na OpenWrt routery.

SSH / monitoring
----------------
- Live Topology backend: 5 s -> 15 s.
- Live Topology frontend: 5 s -> 15 s.
- Legacy snapshot refresh: minimálně 60 s místo 30 s.
- LAN protection scan: 30 s -> 60 s.
- LAN port control už neposílá každých 5 s znovu `ip link set ... down` na již zablokovaný port.
- Stav blokovaného portu se bere z existujícího Live Topology vzorku bez dalšího SSH.
- Pokud je blokovaný port už DOWN, nevznikne kvůli enforce žádná SSH relace.
- Po rebootu routeru Live Topology zjistí port UP a blokace se jednorázově obnoví.
- Při chybě se stejná akce neopakuje rychleji než po 60 s.
- Pokud Live Topology není dostupná, bezpečnostní fallback reassert proběhne nejvýše jednou za 300 s.
- Ochrana iHost/HASSIO před zablokováním zůstává zachována.

Očekávaný běžný provoz
----------------------
Bez ručních akcí a bez probíhajícího OWUT má běžný router typicky jen několik SSH přihlášení za minutu místo desítek. Přesný počet se může krátkodobě zvýšit při otevření inspektoru, ručním refreshi, obnově blokace, startu Dockeru nebo servisní operaci.

UI / verzování
--------------
- Hlavní název: OpenWRT MESH CONTROLLER PRO · v.7.0.0
- Podtitulek zůstává SONOFF iHost · DOCKER · aktuální LAN IP.
- Browser title obsahuje v.7.0.0.
- Další releasy pokračují verzováním v7.x.x.

Bezpečnost a existující funkce
------------------------------
- Persistent Operation Manager zůstává jediným vlastníkem automatického OWUT scheduleru.
- Extroot double-reboot / UUID recovery z v6.3.8–v6.3.9 se nemění.
- LAN blokace zůstávají uložené v /data a po rebootu routeru se znovu aplikují.
- Žádná změna neformátuje ani nemění USB Extroot.

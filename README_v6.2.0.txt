OpenWRT MESH CONTROLLER PRO v6.2.0
==================================

Novinka: runtime blokování fyzických LAN portů přímo z dlaždic LAN PORTY.

- dvojklik na LAN1–LAN4 = okamžitě zablokovat / znovu povolit port
- bez potvrzovacího dialogu; akce se provede pouze dvojklikem
- blokovaný port je červený a přeškrtnutý, stav BLOKOVÁN
- OpenWrt UCI konfigurace se NEMĚNÍ
- blokace používá pouze runtime `ip link set dev lanX down/up`
- požadovaný stav je uložen v `/data/lan_port_state.json`
- po rebootu routeru jsou porty nejdřív standardně povolené a Controller uložené blokace automaticky znovu aplikuje
- watchdog kontroluje blokované porty každých 5 s
- iHost 192.168.30.186 a HASSIO 192.168.30.223 jsou chráněné
- chráněná dlaždice Home Assistantu se zobrazuje jako CHRÁNĚN · HASSIO
- ochrana se určuje přes IP -> MAC -> bridge FDB -> fyzický lanX
- poslední známé umístění chráněných zařízení se ukládá do /data
- chráněný port nelze dvojklikem zablokovat a dvojklik na něm neotevírá dialog
- při nalezení chráněného zařízení na dříve blokovaném portu má ochrana přednost a port se automaticky povolí

Release zachovává stabilní topologii, klienty, LAN TTL, WAN statistiky, OWUT, zálohy a Operation Manager z v6.1.0.

OpenWRT MESH CONTROLLER PRO v6.0.0
==================================

NOVINKA: TICHÁ STARTUP KONTROLA AP INACTIVITY

Při každém startu procesu Controlleru se na pozadí zkontroluje:
  ROUTER 192.168.30.1
  MESH1  192.168.30.2
  MESH2  192.168.30.3
  MESH3  192.168.30.4
  MESH4  192.168.30.5

Kontrolují se VÝHRADNĚ sekce wireless typu wifi-iface s:
  option mode 'ap'

Požadované hodnoty:
  option max_inactivity '60'
  option skip_inactivity_poll '0'

IDEMPOTENCE / OCHRANA FLASH
- Pokud jsou obě hodnoty správně, proběhnou pouze čtecí UCI dotazy.
- Žádné `uci set` ani `uci commit` se v tomto případě neprovedou.
- Pokud některá hodnota chybí nebo je jiná, opraví se pouze tato AP sekce.
- `uci commit wireless` se provede právě jednou na daném routeru a pouze pokud byla změna.
- Při dalším startu Controlleru už bude kontrola pouze čtecí, dokud konfiguraci někdo nezmění/nerestauruje.

BEZPEČNOST SÍTĚ
- mode='mesh' se nikdy nemění.
- mode='sta' se nikdy nemění.
- SSID, hesla, rádia, kanály, 802.11r/k/v, DAWN ani network se nemění.
- Nespouští se `wifi reload`.
- Nespouští se restart network.
- Nespouští se reboot routeru.
- Změna se tedy bezpečně uloží do /etc/config/wireless pro budoucí backup.
- Do běžícího hostapd se aplikuje až při příštím normálním Wi-Fi reloadu/rebootu.

STARTUP / NÁVRAT SÍTĚ
- První kontrola čeká standardně 20 s po startu Controlleru.
- Nedostupný router se zkouší znovu po 30 s, maximálně 20 pokusů.
- Router, který už byl v daném startu úspěšně zkontrolován, se znovu nekontroluje.

DIAGNOSTIKA (bez zápisu na SD)
  GET /api/v600/wifi-ap-policy

Vrací stav pouze z RAM: počet nalezených AP, zda se něco změnilo, zda proběhl commit,
seznam změněných sekcí a případnou SSH chybu.

ZACHOVÁNO Z v5.0.7
- live klienti 2.4 GHz / 5 GHz / celkem přes hostapd get_clients
- live topologie / mesh dBm / bitrate
- iHOST CPU/RAM/TEMP dlaždice
- WAN DOWNLOAD/UPLOAD + historie
- persistentní Operation Manager pro rolling REBOOT a OWUT

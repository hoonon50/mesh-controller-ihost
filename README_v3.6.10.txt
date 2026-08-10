OpenWRT MESH CONTROLLER PRO v3.6.10

Tato aktualizace se aplikuje nad existujici zdrojovou verzi v3.6.8.
Nemeni klienty, zalohy, LAN porty, topologii ani udrzbu.

Nova funkce v topologii routeru:
CPU 52 °C
UPTIME 4d 7h

Hodnoty se nacitaji pres SSH primo z routeru:
- CPU: /sys/class/thermal/thermal_zone*/temp
- UPTIME: /proc/uptime

Obnova hodnot: kazdych 10 minut.
Navic je odstranena zbytecna DOM refresh smycka, ktera mohla zpusobovat blikani dlazdic.

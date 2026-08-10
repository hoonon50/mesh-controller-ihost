OpenWRT MESH CONTROLLER PRO v3.6.11

Oprava blikani CPU/UPTIME dlazdic:
- CPU + UPTIME se dale nacitaji pouze 1x za 10 minut
- odstranena 120ms prodleva po prekresleni topologie
- health blok ma trvale rezervovanou vysku
- pri beznem refreshi se zachovaji posledni zname hodnoty
- pri jednorazove chybe SSH se posledni hodnota nesmaze

Vzhled:
MESH2
192.168.30.3
CPU 52 °C
UPTIME 4d 7h

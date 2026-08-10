OpenWRT MESH CONTROLLER PRO v3.8.6

Opravy:
- Jasna volba Frekvence: Kazdy den / Vybrany den.
- Scheduler umi skutecny denni beh nezavisle na dni v tydnu.
- Automaticke OWUT reporty pouzivaji robustni doruceni se stejnym Gmail SMTP nastavenim jako testovaci e-mail.
- Chyba teplot nebo HTML renderu uz nezabrani reportu; pouzije se nouzovy TEXT report.
- Pri chybe odeslani se report ulozi do /data/owut_pending_mail.json a retry loop jej zkusi znovu kazdych 5 minut.
- Uklada se posledni stav automatickeho reportu pro diagnostiku.
- Ostatni dashboard/layout/refresh se nemeni.

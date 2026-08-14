OpenWRT MESH CONTROLLER PRO v6.1.0
==================================

CLEANUP RELEASE
- Funkční základ v6.0.9 zůstává zachovaný.
- Bez změny klientské, LAN, WAN, OWUT, reboot a Wi-Fi policy logiky.

SJEDNOCENÍ VERZÍ
- Runtime backend /api/v503/live-topology se při buildu nastaví na 6.1.0.
- Frontend LIVE označení se při buildu nastaví na 6.1.0.
- Cache tagy v503 CSS/JS jsou 6.1.0.
- GitHub Actions publikuje GHCR tagy :latest a :6.1.0.
- docker-compose používá lokální tag 6.1.0.

DOKUMENTACE A BEZPEČNOST
- README_CZ aktualizováno na současný stav projektu.
- config.example.json už nepoužívá ukázkové heslo root/root; obsahuje CHANGE_ME.
- Existující /data/config.json se nemění, takže update nerozbije současné SSH připojení.
- Runtime SSH fallback zůstává kvůli zpětné kompatibilitě zachovaný; doporučeno změnit slabá hesla routerů.

PERSISTENCE
- /data/config.json zachováno.
- /data/backups zachováno.
- /data/wan_usage.json zachováno.
- /data/mesh_operation.json zachováno.

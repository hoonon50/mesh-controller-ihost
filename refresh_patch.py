from pathlib import Path
import re

# Jemné doladění stávajícího frontendu. Nezasahujeme do CPU/UPTIME (v369.js),
# které zůstává na 10 minut. Pokud app.js používá samostatný interval pro
# topologii/stav, nastavíme jej na 10 s. Klient/LAN intervaly ponecháme 30 s.
app_js = Path('/app/static/app.js')
if not app_js.exists():
    raise SystemExit(0)

text = app_js.read_text(encoding='utf-8')
original = text

# Pojmenované konstanty – bezpečné a jednoznačné.
for name in ('TOPOLOGY_REFRESH_MS', 'MESH_REFRESH_MS', 'STATUS_REFRESH_MS', 'NODE_REFRESH_MS', 'ONLINE_REFRESH_MS', 'STATE_REFRESH_MS', 'AUTO_REFRESH_MS', 'REFRESH_INTERVAL_MS'):
    text = re.sub(rf'(\b{re.escape(name)}\s*=\s*)\d+', rf'\g<1>10000', text)
for name in ('CLIENT_REFRESH_MS', 'CLIENTS_REFRESH_MS', 'LAN_REFRESH_MS', 'PORTS_REFRESH_MS'):
    text = re.sub(rf'(\b{re.escape(name)}\s*=\s*)\d+', rf'\g<1>30000', text)

# Samostatné setInterval callbacky podle názvu callbacku.
def tune_interval(match):
    callback = match.group('cb')
    ms = int(match.group('ms'))
    low = callback.lower()
    if 'client' in low or 'lan' in low or 'port' in low:
        target = 30000
    elif any(k in low for k in ('topology', 'mesh', 'status', 'node', 'online', 'state', 'refresh')):
        target = 10000
    else:
        return match.group(0)
    return f"setInterval({callback}, {target})"

text = re.sub(
    r'setInterval\(\s*(?P<cb>[A-Za-z_$][\w$]*(?:\s*\([^)]*\))?|\(\s*\)\s*=>\s*[A-Za-z_$][\w$]*\([^)]*\))\s*,\s*(?P<ms>\d{4,7})\s*\)',
    tune_interval,
    text,
)

if text != original:
    app_js.write_text(text, encoding='utf-8')
    print('v3.8.1: app.js refresh intervals tuned')
else:
    print('v3.8.1: no safely identifiable app.js topology timer; main refresh left unchanged')

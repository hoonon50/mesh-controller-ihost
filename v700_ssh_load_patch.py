from pathlib import Path
import os
import re

VERSION = "7.0.0"
ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
APP = ROOT / "app.py"
INDEX = ROOT / "templates" / "index.html"
STYLE = ROOT / "static" / "style.css"
APP_JS = ROOT / "static" / "app.js"
LIVE = ROOT / "live_topology_v503.py"
LIVE_JS = ROOT / "static" / "v503_live_topology.js"
LAN = ROOT / "lan_port_control_v620.py"
LAN_JS = ROOT / "static" / "v620_lan_port_control.js"
OPS = ROOT / "mesh_operation_manager.py"
OWUT = ROOT / "owut_manager.py"
V500_JS = ROOT / "static" / "v500_operation.js"
VERSIONED_MODULES = [
    ROOT / "topology_inspector_v631.py",
    ROOT / "lan_port_inspector_v630.py",
    ROOT / "client_ip_resolver_v632.py",
]


def sub_once(text: str, pattern: str, repl: str, label: str, flags: int = 0) -> str:
    new, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"v{VERSION}: nenalezen patch bod: {label}")
    return new


# ---------------------------------------------------------------- live topology
live = LIVE.read_text(encoding="utf-8")
live = sub_once(
    live,
    r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$',
    f'VERSION = "{VERSION}"',
    "live version",
)
live = sub_once(
    live,
    r'(?m)^POLL_SECONDS\s*=\s*max\([^\n]+$',
    'POLL_SECONDS = max(10, int(os.environ.get("MESH_LIVE_TOPOLOGY_POLL", "15")))',
    "live poll",
)
live = sub_once(
    live,
    r'(?m)^HEALTH_SECONDS\s*=\s*max\([^\n]+$',
    'HEALTH_SECONDS = max(POLL_SECONDS, int(os.environ.get("MESH_LIVE_HEALTH_POLL", "30")))',
    "health poll",
)
LIVE.write_text(live, encoding="utf-8")

js = LIVE_JS.read_text(encoding="utf-8")
js = sub_once(js, r'const REFRESH_MS\s*=\s*\d+;', 'const REFRESH_MS = 15000;', "live frontend poll")
js = re.sub(r'__MESH_V\d+_LIVE_TOPOLOGY__', '__MESH_V700_LIVE_TOPOLOGY__', js)
js = re.sub(r'LIVE v\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?', f'LIVE v{VERSION}', js)
js = js.replace('payload.poll_seconds || 5', 'payload.poll_seconds || 15')
LIVE_JS.write_text(js, encoding="utf-8")


# ----------------------------------------------------------- LAN block control
lan = LAN.read_text(encoding="utf-8")
lan = sub_once(
    lan,
    r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$',
    f'VERSION = "{VERSION}"',
    "LAN version",
)
lan = sub_once(
    lan,
    r'(?m)^WATCH_SECONDS\s*=\s*max\([^\n]+$',
    'WATCH_SECONDS = max(15, int(os.environ.get("MESH_LAN_PORT_WATCH_SECONDS", "15")))',
    "LAN watch",
)
lan = sub_once(
    lan,
    r'(?m)^PROTECT_SCAN_SECONDS\s*=\s*max\([^\n]+$',
    'PROTECT_SCAN_SECONDS = max(30, int(os.environ.get("MESH_LAN_PROTECT_SCAN_SECONDS", "60")))\nREASSERT_SECONDS = max(60, int(os.environ.get("MESH_LAN_REASSERT_SECONDS", "300")))\nACTION_RETRY_SECONDS = max(30, int(os.environ.get("MESH_LAN_ACTION_RETRY_SECONDS", "60")))',
    "LAN protect/reassert intervals",
)
lan = sub_once(
    lan,
    r'(\s+self\.last_scan\s*=\s*0\.0\n)',
    r'\1        self.app = None\n        self._last_reassert: Dict[str, float] = {}\n',
    "LAN runtime state",
)

enforce_pattern = r'''    def enforce\(self\) -> None:\n.*?(?=\n    def _loop\(self\) -> None:)'''
enforce_replacement = '''    def _live_port_up(self, ip: str, port: str) -> Optional[bool]:
        """Vrátí čerstvý stav portu z Live Topology bez dalšího SSH.

        True  = port je fyzicky UP a uloženou blokaci je potřeba aplikovat.
        False = port už je DOWN, žádné SSH není potřeba.
        None  = čerstvý live vzorek není dostupný; použije se pomalý fallback.
        """
        app = getattr(self, "app", None)
        if app is None or not hasattr(app, "extensions"):
            return None
        try:
            collector = app.extensions.get("live_topology_v503")
            if collector is None:
                return None
            snap = collector.snapshot()
        except Exception:
            return None
        for node in snap.get("nodes", []) or []:
            if not isinstance(node, dict) or str(node.get("ip") or "") != ip:
                continue
            if not node.get("online") or node.get("stale"):
                return None
            for row in node.get("ports", []) or []:
                if isinstance(row, dict) and str(row.get("name") or "").lower() == port:
                    return bool(row.get("up"))
            return None
        return None

    def enforce(self) -> None:
        """Obnovuje uložené blokace bez periodického SSH bombardování.

        V běžném stavu je port podle Live Topology už DOWN a neotevře se žádné
        SSH. Po rebootu routeru Live Topology uvidí port jako UP a následuje
        právě jeden opravný `ip link set ... down`. Pokud live collector není
        dostupný, použije se pouze pomalý REASSERT_SECONDS fallback.
        """
        with self.lock:
            blocked = {
                ip: list(ports)
                for ip, ports in self.state.get("blocked", {}).items()
                if isinstance(ports, list)
            }

        now = time.monotonic()
        active_keys: set[str] = set()
        for ip, ports in blocked.items():
            for port in ports:
                key = f"{ip}/{port}"
                active_keys.add(key)
                with self.lock:
                    if self._is_protected_locked(ip, port):
                        continue
                    last_attempt = float(self._last_reassert.get(key, 0.0) or 0.0)

                live_up = self._live_port_up(ip, port)
                if live_up is False:
                    # Port je již administrativně/fyzicky dole: nulové SSH.
                    continue
                if live_up is True:
                    # Po restartu může být chvíli UP. Případnou chybu neopakuj
                    # rychleji než ACTION_RETRY_SECONDS.
                    if last_attempt and now - last_attempt < ACTION_RETRY_SECONDS:
                        continue
                else:
                    # Bez čerstvého live vzorku nedělej 15s blind reassert.
                    if last_attempt and now - last_attempt < REASSERT_SECONDS:
                        continue

                with self.lock:
                    self._last_reassert[key] = now
                ok, detail = self._set_link(ip, port, True)
                with self.lock:
                    if ok:
                        self.last_errors.pop(key, None)
                    else:
                        self.last_errors[key] = detail

        with self.lock:
            for key in list(self._last_reassert):
                if key not in active_keys:
                    self._last_reassert.pop(key, None)
'''
lan, count = re.subn(enforce_pattern, enforce_replacement, lan, count=1, flags=re.S)
if count != 1:
    raise SystemExit(f"v{VERSION}: LAN enforce() blok nenalezen")

lan = sub_once(
    lan,
    r'(\n\s*lan_port_controller\.start\(\)\n\s*return lan_port_controller)',
    '\n    lan_port_controller.app = app\n    lan_port_controller.start()\n    return lan_port_controller',
    "LAN app binding",
)
LAN.write_text(lan, encoding="utf-8")

lan_js = LAN_JS.read_text(encoding="utf-8")
lan_js = sub_once(lan_js, r'const POLL_MS\s*=\s*\d+;', 'const POLL_MS = 15000;', "LAN UI poll")
lan_js = lan_js.replace("console.error('v6.2.0 LAN port state:', err);", "console.error('v7.0.0 LAN port state:', err);")
LAN_JS.write_text(lan_js, encoding="utf-8")


# --------------------------------------------------------------- legacy status
app = APP.read_text(encoding="utf-8")
app = sub_once(
    app,
    r'time\.sleep\(max\(15, seconds\)\)',
    'time.sleep(max(60, seconds))',
    "legacy refresh minimum",
)
APP.write_text(app, encoding="utf-8")

app_js = APP_JS.read_text(encoding="utf-8")
# Starší build patch může hodnotu 30000 před v7.0.0 změnit. Záměrně tedy
# hledáme konkrétní timer loadStatus s libovolným číselným intervalem.
app_js = sub_once(app_js, r'setInterval\(loadStatus,\s*\d+\)', 'setInterval(loadStatus,60000)', "legacy UI status poll")
APP_JS.write_text(app_js, encoding="utf-8")


# --------------------------------------------------------------------- version
for module in VERSIONED_MODULES:
    if not module.exists():
        continue
    text = module.read_text(encoding="utf-8")
    text, count = re.subn(
        r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$',
        f'VERSION = "{VERSION}"',
        text,
        count=1,
    )
    if count:
        module.write_text(text, encoding="utf-8")

if OPS.exists():
    ops = OPS.read_text(encoding="utf-8")
    ops = re.sub(r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$', f'VERSION = "{VERSION}"', ops, count=1)
    ops = re.sub(r'START v\d+\.\d+\.\d+:', f'START v{VERSION}:', ops)
    ops = re.sub(r'Persistent Operation Manager v\d+\.\d+\.\d+', f'Persistent Operation Manager v{VERSION}', ops)
    ops = re.sub(r'OpenWRT MESH CONTROLLER PRO v\d+\.\d+\.\d+', f'OpenWRT MESH CONTROLLER PRO v{VERSION}', ops)
    OPS.write_text(ops, encoding="utf-8")

if OWUT.exists():
    owut = OWUT.read_text(encoding="utf-8")
    owut = re.sub(r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$', f'VERSION = "{VERSION}"', owut, count=1)
    OWUT.write_text(owut, encoding="utf-8")

if V500_JS.exists():
    v500 = V500_JS.read_text(encoding="utf-8")
    v500 = re.sub(r'<span class="v500-version">v[^<]+</span>', f'<span class="v500-version">v{VERSION}</span>', v500)
    V500_JS.write_text(v500, encoding="utf-8")

html = INDEX.read_text(encoding="utf-8")
html = sub_once(html, r'<title>.*?</title>', f'<title>OpenWRT MESH CONTROLLER PRO · v.{VERSION}</title>', "browser title", flags=re.S)
# Šablona na release větvi už může mít verzi vloženou přímo. Patch je proto
# idempotentní a zároveň zachovává samostatný přesný textový uzel názvu, který
# používá live-topology frontend k nalezení headeru.
if 'class="app-version"' in html:
    html = sub_once(
        html,
        r'<span class="app-version">v\.[^<]+</span>',
        f'<span class="app-version">v.{VERSION}</span>',
        "header existing version",
    )
else:
    html = sub_once(
        html,
        r'<h1>\s*OpenWRT MESH CONTROLLER PRO\s*</h1>',
        f'<h1><span>OpenWRT MESH CONTROLLER PRO</span><span class="app-version">v.{VERSION}</span></h1>',
        "header title/version",
    )
html = re.sub(r'(/static/app\.js\?v=)[^"\']+', rf'\g<1>{VERSION}', html)
html = re.sub(r'(/static/style\.css\?v=)[^"\']+', rf'\g<1>{VERSION}', html)
html = re.sub(r'(/static/v503_live_topology\.(?:css|js)\?v=)[^"\']+', rf'\g<1>{VERSION}', html)
html = re.sub(r'(/static/v620_lan_port_control\.(?:css|js)\?v=)[^"\']+', rf'\g<1>{VERSION}', html)
html = re.sub(r'(/static/v500_operation\.(?:css|js)\?v=)[^"\']+', rf'\g<1>{VERSION}', html)
INDEX.write_text(html, encoding="utf-8")

style = STYLE.read_text(encoding="utf-8")
if '.app-version{' not in style and '.app-version {' not in style:
    style += '''\n/* v7.0.0 – viditelné verzování aplikace v hlavičce */\n.app-version{font-size:.56em;font-weight:800;color:var(--muted);margin-left:10px;vertical-align:middle;white-space:nowrap}\n'''
STYLE.write_text(style, encoding="utf-8")

# ------------------------------------------------------------- build safeguards
checks = {
    "live backend 15s": 'MESH_LIVE_TOPOLOGY_POLL", "15"' in LIVE.read_text(encoding="utf-8"),
    "live frontend 15s": 'const REFRESH_MS = 15000;' in LIVE_JS.read_text(encoding="utf-8"),
    "LAN state-aware": 'def _live_port_up' in LAN.read_text(encoding="utf-8"),
    "LAN no blind 5s": 'Port je již administrativně/fyzicky dole: nulové SSH.' in LAN.read_text(encoding="utf-8"),
    "legacy refresh 60s": 'time.sleep(max(60, seconds))' in APP.read_text(encoding="utf-8"),
    "legacy UI 60s": 'setInterval(loadStatus,60000)' in APP_JS.read_text(encoding="utf-8"),
    "UI version": f'v.{VERSION}' in INDEX.read_text(encoding="utf-8"),
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit(f"v{VERSION}: build safeguard selhal: {', '.join(failed)}")

print(f"v{VERSION}: SSH load reduced – live topology 15 s, legacy snapshot >= 60 s")
print(f"v{VERSION}: blocked LAN ports are reasserted only when live state says UP; no blind 5 s SSH loop")
print(f"v{VERSION}: protected-host scan 60 s, fallback reassert 300 s, failed action retry >= 60 s")
print(f"v{VERSION}: UI/browser title now shows OpenWRT MESH CONTROLLER PRO · v.{VERSION}")

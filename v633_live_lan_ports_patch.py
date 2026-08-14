from pathlib import Path
import os
import re

VERSION = "6.3.3"
ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
LIVE = ROOT / "live_topology_v503.py"
LIVE_JS = ROOT / "static" / "v503_live_topology.js"
INDEX = ROOT / "templates" / "index.html"
VERSIONED_MODULES = [
    ROOT / "topology_inspector_v631.py",
    ROOT / "lan_port_inspector_v630.py",
    ROOT / "client_ip_resolver_v632.py",
]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"v{VERSION}: nenalezen patch bod: {label}")
    return text.replace(old, new, 1)


if not LIVE.exists() or not LIVE_JS.exists():
    raise SystemExit(f"v{VERSION}: live topology soubory nenalezeny")

live = LIVE.read_text(encoding="utf-8")
live = re.sub(r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$', f'VERSION = "{VERSION}"', live, count=1)

# Každý node má explicitní pole ports i před prvním úspěšným vzorkem / při offline stavu.
if '"ports": [],' not in live:
    live = re.sub(
        r'(?m)^(\s*)"lan_client_macs": \[\],$',
        lambda m: f'{m.group(1)}"lan_client_macs": [],\n{m.group(1)}"ports": [],',
        live,
    )

# Fyzický stav LAN1-LAN4 načteme ve stejném SSH vzorku jako Wi-Fi/FDB, tedy bez dalšího SSH spojení.
if "__PORTS_BEGIN__" not in live:
    anchor = "printf '__FDB_END__\\n'\n'''"
    port_shell = """printf '__FDB_END__\\n'

printf '__PORTS_BEGIN__\\n'
for P in lan1 lan2 lan3 lan4; do
  [ -e "/sys/class/net/$P" ] || continue
  OPER="$(cat /sys/class/net/$P/operstate 2>/dev/null || echo unknown)"
  CARRIER="$(cat /sys/class/net/$P/carrier 2>/dev/null || echo 0)"
  SPEED="$(cat /sys/class/net/$P/speed 2>/dev/null || true)"
  case "$SPEED" in ''|*[!0-9]*) SPEED='' ;; esac
  printf '%s\\t%s\\t%s\\t%s\\n' "$P" "$OPER" "$CARRIER" "$SPEED"
done
printf '__PORTS_END__\\n'
'''"""
    live = replace_once(live, anchor, port_shell, "live port shell collection")

parser_marker = "        # v6.3.3 live physical LAN ports\n"
if parser_marker not in live:
    anchor = "        try:\n            uptime_s: Optional[int] = int(float(sys_values.get(\"UPTIME\", \"\")))\n"
    parser = '''        # v6.3.3 live physical LAN ports
        ports: List[Dict[str, Any]] = []
        ports_match = re.search(r"__PORTS_BEGIN__\\n(.*?)__PORTS_END__", out, re.S)
        if ports_match:
            for raw in ports_match.group(1).splitlines():
                parts = raw.strip().split("\\t")
                if len(parts) < 3 or not re.fullmatch(r"lan[1-4]", parts[0], re.I):
                    continue
                pname = parts[0].lower()
                oper = parts[1].strip().lower() or "unknown"
                carrier = parts[2].strip() == "1"
                speed = None
                if len(parts) > 3 and parts[3].strip().isdigit():
                    value = int(parts[3].strip())
                    if value > 0:
                        speed = value
                ports.append({
                    "name": pname,
                    "up": carrier,
                    "operstate": oper,
                    "carrier": 1 if carrier else 0,
                    "speed_mbps": speed,
                })
        ports.sort(key=lambda row: int(str(row.get("name") or "lan99")[3:]) if str(row.get("name") or "").startswith("lan") else 99)

'''
    live = replace_once(live, anchor, parser + anchor, "live port parser")

if '            "ports": ports,\n' not in live:
    live = replace_once(
        live,
        '            "lan_client_macs": sorted(lan_macs),\n            "_lan_observed_macs": sorted(lan_macs),\n',
        '            "lan_client_macs": sorted(lan_macs),\n            "ports": ports,\n            "_lan_observed_macs": sorted(lan_macs),\n',
        "live node ports payload",
    )

LIVE.write_text(live, encoding="utf-8")

# Inspektory/resolver hlásí stejnou release verzi, jejich funkční logika se nemění.
for module in VERSIONED_MODULES:
    if not module.exists():
        continue
    text = module.read_text(encoding="utf-8")
    text = re.sub(r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$', f'VERSION = "{VERSION}"', text, count=1)
    module.write_text(text, encoding="utf-8")

js = LIVE_JS.read_text(encoding="utf-8")
js = re.sub(r'__MESH_V\d+_LIVE_TOPOLOGY__', '__MESH_V633_LIVE_TOPOLOGY__', js)
js = re.sub(r'LIVE v\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?', f'LIVE v{VERSION}', js)

js_marker = "  // v6.3.3 live LAN1-LAN4 tiles\n"
if js_marker not in js:
    anchor = "  function render(payload) {\n"
    block = r'''  // v6.3.3 live LAN1-LAN4 tiles
  let livePortsObserver = null;

  function livePortClass(port) {
    if (!port || !port.up) return 'port-down';
    const speed = Number(port.speed_mbps || 0);
    if (speed >= 1000) return 'port-gigabit';
    if (speed > 0) return 'port-fast';
    return 'port-up';
  }

  function updateLivePorts(nodesPayload) {
    const grid = document.getElementById('portsGrid');
    if (!grid) return;
    const byIp = new Map((nodesPayload || []).map(node => [String(node.ip || ''), node]));

    grid.querySelectorAll('.router-ports').forEach(section => {
      const ip = (section.querySelector('.router-ports-head span')?.textContent || '').trim();
      const node = byIp.get(ip);
      if (!node || !node.online || node.stale || !Array.isArray(node.ports)) return;
      const ports = new Map(node.ports.map(port => [String(port.name || '').toLowerCase(), port]));

      section.querySelectorAll('.port-tile').forEach(tile => {
        const m = (tile.querySelector(':scope > strong')?.textContent || '').trim().match(/^LAN([1-4])$/i);
        if (!m) return;
        const port = ports.get(`lan${m[1]}`);
        if (!port) return;

        tile.classList.remove('port-down', 'port-gigabit', 'port-fast', 'port-up');
        tile.classList.add(livePortClass(port));
        tile.dataset.v633LivePort = '1';

        const speed = tile.querySelector(':scope > span');
        if (speed) {
          speed.textContent = port.up
            ? (Number(port.speed_mbps || 0) > 0 ? `${Number(port.speed_mbps)} Mbit/s` : 'RYCHLOST ?')
            : '—';
        }

        const status = tile.querySelector(':scope > b');
        if (status) {
          const liveStatus = port.up ? 'UP' : 'DOWN';
          // v6.2.0 si původní stav ukládá do datasetu. Aktualizujeme i jej,
          // aby jeho 5s decorate() nevracel zastaralé UP/DOWN.
          status.dataset.v620Original = liveStatus;
          if (!tile.classList.contains('v620-port-blocked')) status.textContent = liveStatus;
        }
      });
    });
  }

  function ensureLivePortsObserver() {
    const grid = document.getElementById('portsGrid');
    if (!grid || livePortsObserver) return;
    // Starý /api/status renderer může po 30 s vyměnit celé router-ports sekce.
    // Reaplikujeme poslední 5s live vzorek hned po takové výměně.
    livePortsObserver = new MutationObserver(() => {
      window.setTimeout(() => {
        if (lastPayload) updateLivePorts(lastPayload.nodes || []);
      }, 0);
    });
    livePortsObserver.observe(grid, {childList: true});
  }

'''
    js = replace_once(js, anchor, block + anchor, "live port frontend helpers")

render_anchor = "    for (const node of (payload.nodes || [])) updateNode(node);\n    drawLinks(payload.links || []);\n"
render_repl = "    for (const node of (payload.nodes || [])) updateNode(node);\n    ensureLivePortsObserver();\n    updateLivePorts(payload.nodes || []);\n    drawLinks(payload.links || []);\n"
if render_repl not in js:
    js = replace_once(js, render_anchor, render_repl, "live port render hook")

LIVE_JS.write_text(js, encoding="utf-8")

# Po všech starších patchích přepiš cache tag live assetu na aktuální release.
if INDEX.exists():
    html = INDEX.read_text(encoding="utf-8")
    html = re.sub(
        r'(<link\s+[^>]*href=["\']/static/v503_live_topology\.css\?v=)[^"\']+(["\'][^>]*>)',
        rf'\g<1>{VERSION}\2', html, flags=re.I,
    )
    html = re.sub(
        r'(<script\s+[^>]*src=["\']/static/v503_live_topology\.js\?v=)[^"\']+(["\'][^>]*></script>)',
        rf'\g<1>{VERSION}\2', html, flags=re.I,
    )
    INDEX.write_text(html, encoding="utf-8")

print(f"v{VERSION}: physical LAN1-LAN4 state joined to the 5s live topology sample")
print(f"v{VERSION}: existing LAN tiles are updated in-place; block/protection state is preserved")

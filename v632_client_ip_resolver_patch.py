from pathlib import Path
import os
import re

VERSION = "6.3.2"
ROOT = Path(os.environ.get("MESH_APP_ROOT", "/app"))
TOPOLOGY = ROOT / "topology_inspector_v631.py"
LAN = ROOT / "lan_port_inspector_v630.py"
LIVE = ROOT / "live_topology_v503.py"
LIVE_JS = ROOT / "static" / "v503_live_topology.js"
INDEX = ROOT / "templates" / "index.html"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"v{VERSION}: nenalezen patch bod: {label}")
    return text.replace(old, new, 1)


# Topology inspector: Wi-Fi/LAN MAC bez známé IPv4 aktivně dohledá přes MAIN router.
if not TOPOLOGY.exists():
    raise SystemExit(f"v{VERSION}: topology_inspector_v631.py nenalezen")
top = TOPOLOGY.read_text(encoding="utf-8")
if "from client_ip_resolver_v632 import resolve_client_ipv4" not in top:
    top = replace_once(
        top,
        "from mesh_core import controller\n",
        "from mesh_core import controller\nfrom client_ip_resolver_v632 import resolve_client_ipv4\n",
        "topology resolver import",
    )
top = re.sub(r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$', f'VERSION = "{VERSION}"', top, count=1)

marker = "    # v6.3.2 active MAC -> IPv4 resolution\n"
if marker not in top:
    anchor = "    def device(mac: str) -> Dict[str, str]:\n"
    block = (
        marker
        + "    all_client_macs: set[str] = set(wifi5) | set(wifi24)\n"
        + "    for _macs in lan_by_port.values():\n"
        + "        all_client_macs.update(_macs)\n"
        + "    unresolved_macs = {\n"
        + "        mac for mac in all_client_macs\n"
        + "        if not (\n"
        + "            neigh_by_mac.get(mac)\n"
        + "            or lease_by_mac.get(mac, {}).get(\"ip\", \"\")\n"
        + "            or snapshot_by_mac.get(mac, {}).get(\"ip\", \"\")\n"
        + "        )\n"
        + "    }\n"
        + "    resolved_ipv4 = resolve_client_ipv4(unresolved_macs) if unresolved_macs else {}\n\n"
    )
    top = replace_once(top, anchor, block + anchor, "topology active resolver block")

top = replace_once(
    top,
    '        dip = neigh_by_mac.get(mac) or lease.get("ip", "") or snap.get("ip", "")\n',
    '        dip = neigh_by_mac.get(mac) or lease.get("ip", "") or snap.get("ip", "") or resolved_ipv4.get(mac, "")\n',
    "topology resolved IPv4 fallback",
)
TOPOLOGY.write_text(top, encoding="utf-8")


# LAN port inspector: stejný resolver pro MAC za fyzickým lanX.
if not LAN.exists():
    raise SystemExit(f"v{VERSION}: lan_port_inspector_v630.py nenalezen")
lan = LAN.read_text(encoding="utf-8")
if "from client_ip_resolver_v632 import resolve_client_ipv4" not in lan:
    lan = replace_once(
        lan,
        "from mesh_core import controller\n",
        "from mesh_core import controller\nfrom client_ip_resolver_v632 import resolve_client_ipv4\n",
        "LAN resolver import",
    )
lan = re.sub(r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$', f'VERSION = "{VERSION}"', lan, count=1)

lan_marker = "    # v6.3.2 active MAC -> IPv4 resolution\n"
if lan_marker not in lan:
    anchor = "    devices: List[Dict[str, str]] = []\n"
    block = (
        lan_marker
        + "    unresolved_macs = {\n"
        + "        mac for mac in fdb_macs\n"
        + "        if not (\n"
        + "            neigh_by_mac.get(mac)\n"
        + "            or lease_by_mac.get(mac, {}).get(\"ip\", \"\")\n"
        + "            or snapshot_by_mac.get(mac, {}).get(\"ip\", \"\")\n"
        + "        )\n"
        + "    }\n"
        + "    resolved_ipv4 = resolve_client_ipv4(unresolved_macs) if unresolved_macs else {}\n\n"
    )
    lan = replace_once(lan, anchor, block + anchor, "LAN active resolver block")

lan = replace_once(
    lan,
    '        device_ip = neigh_by_mac.get(mac) or lease.get("ip", "") or snap.get("ip", "")\n',
    '        device_ip = neigh_by_mac.get(mac) or lease.get("ip", "") or snap.get("ip", "") or resolved_ipv4.get(mac, "")\n',
    "LAN resolved IPv4 fallback",
)
LAN.write_text(lan, encoding="utf-8")


# Release/runtime verze: funkční topology collector zůstává stejný.
if LIVE.exists():
    live = LIVE.read_text(encoding="utf-8")
    live = re.sub(r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']\s*$', f'VERSION = "{VERSION}"', live, count=1)
    LIVE.write_text(live, encoding="utf-8")

if LIVE_JS.exists():
    js = LIVE_JS.read_text(encoding="utf-8")
    js = re.sub(r'__MESH_V\d+_LIVE_TOPOLOGY__', '__MESH_V632_LIVE_TOPOLOGY__', js)
    js = re.sub(r'LIVE v\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?', f'LIVE v{VERSION}', js)
    LIVE_JS.write_text(js, encoding="utf-8")

# Vynutí načtení aktuálního live-topology assetu i při upgrade z v6.3.1.
if INDEX.exists():
    html = INDEX.read_text(encoding="utf-8")
    html = re.sub(
        r'(/static/v503_live_topology\.css\?v=)[^"\']+',
        rf'\g<1>{VERSION}',
        html,
    )
    html = re.sub(
        r'(/static/v503_live_topology\.js\?v=)[^"\']+',
        rf'\g<1>{VERSION}',
        html,
    )
    INDEX.write_text(html, encoding="utf-8")

print(f"v{VERSION}: active MAC -> IPv4 resolver integrated into topology and LAN inspectors")
print(f"v{VERSION}: unresolved MACs are actively refreshed through MAIN router ARP/neighbour discovery")

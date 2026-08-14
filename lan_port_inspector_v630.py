from __future__ import annotations

import ipaddress
import re
import shlex
from typing import Any, Dict, List, Tuple

from flask import jsonify, request

from mesh_core import controller

VERSION = "6.3.0"
PORT_RE = re.compile(r"^lan([1-4])$", re.I)
MAC_RE = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$", re.I)

SPECIAL_NAMES = {
    "192.168.30.186": "iHOST",
    "192.168.30.223": "HASSIO",
}


def _router_ips() -> set[str]:
    return {str(r.get("ip") or "") for r in controller.routers}


def _validate(ip: str, port: str) -> Tuple[str, str]:
    ip = str(ip or "").strip()
    port = str(port or "").strip().lower()
    if ip not in _router_ips():
        raise ValueError("Neznámý router")
    if not PORT_RE.fullmatch(port):
        raise ValueError("Neplatný LAN port")
    return ip, port


def _section(text: str, name: str) -> str:
    m = re.search(rf"__{re.escape(name)}_BEGIN__\n(.*?)\n__{re.escape(name)}_END__", text, re.S)
    return m.group(1) if m else ""


def _valid_unicast_mac(mac: str) -> bool:
    mac = str(mac or "").lower()
    if not MAC_RE.fullmatch(mac) or mac == "00:00:00:00:00:00":
        return False
    try:
        first = int(mac.split(":", 1)[0], 16)
    except ValueError:
        return False
    return (first & 1) == 0


def _ip_sort(value: str) -> Tuple[int, int, int, int, str]:
    try:
        addr = ipaddress.ip_address(value)
        if addr.version == 4:
            parts = [int(x) for x in value.split(".")]
            return parts[0], parts[1], parts[2], parts[3], ""
    except ValueError:
        pass
    return 999, 999, 999, 999, value


def _snapshot_clients() -> Tuple[Dict[str, Dict[str, str]], Dict[str, Dict[str, str]]]:
    by_mac: Dict[str, Dict[str, str]] = {}
    by_ip: Dict[str, Dict[str, str]] = {}
    try:
        snap = controller.get_snapshot()
    except Exception:
        return by_mac, by_ip
    for item in snap.get("clients", []) or []:
        if not isinstance(item, dict):
            continue
        mac = str(item.get("mac") or "").lower().strip()
        ip = str(item.get("ip") or "").strip()
        hostname = str(item.get("hostname") or item.get("name") or "").strip()
        row = {"mac": mac, "ip": ip, "hostname": hostname}
        if MAC_RE.fullmatch(mac):
            by_mac[mac] = row
        if ip:
            by_ip[ip] = row
    return by_mac, by_ip


def inspect_port(ip: str, port: str) -> Dict[str, Any]:
    ip, port = _validate(ip, port)
    qport = shlex.quote(port)
    command = f'''PORT={qport}
printf '__LINK_BEGIN__\n'
printf 'OPER=%s\n' "$(cat /sys/class/net/$PORT/operstate 2>/dev/null || echo unknown)"
printf 'CARRIER=%s\n' "$(cat /sys/class/net/$PORT/carrier 2>/dev/null || echo 0)"
printf 'SPEED=%s\n' "$(cat /sys/class/net/$PORT/speed 2>/dev/null || true)"
printf '__LINK_END__\n'

printf '__FDB_BEGIN__\n'
if command -v bridge >/dev/null 2>&1; then
  bridge fdb show dev "$PORT" 2>/dev/null || true
fi
printf '__FDB_END__\n'

printf '__NEIGH_BEGIN__\n'
ip -4 neigh show dev br-lan 2>/dev/null || ip -4 neigh show 2>/dev/null || true
printf '__NEIGH_END__\n'

printf '__LEASES_BEGIN__\n'
cat /tmp/dhcp.leases 2>/dev/null || true
printf '__LEASES_END__\n'

printf '__LOCAL_BEGIN__\n'
for f in /sys/class/net/*/address; do cat "$f" 2>/dev/null; done
printf '__LOCAL_END__\n'
'''

    client = None
    try:
        client = controller.ssh_client(ip, timeout=5)
        out, err, code = controller.command(client, command, timeout=15)
        if code != 0:
            raise RuntimeError((err or out).strip() or f"SSH rc={code}")
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    local_macs = {
        line.strip().lower()
        for line in _section(out, "LOCAL").splitlines()
        if MAC_RE.fullmatch(line.strip())
    }

    fdb_macs: set[str] = set()
    for raw in _section(out, "FDB").splitlines():
        parts = raw.strip().split()
        if not parts:
            continue
        mac = parts[0].lower()
        low = {p.lower() for p in parts[1:]}
        if not _valid_unicast_mac(mac) or mac in local_macs:
            continue
        # Lokální/permanentní FDB položky patří switchi/routeru, ne klientům.
        if "self" in low or "permanent" in low or "local" in low:
            continue
        fdb_macs.add(mac)

    neigh_by_mac: Dict[str, str] = {}
    for raw in _section(out, "NEIGH").splitlines():
        m = re.match(
            r"^(\S+)\s+dev\s+\S+.*?\slladdr\s+([0-9a-f:]{17})\b",
            raw.strip(),
            re.I,
        )
        if not m:
            continue
        nip, mac = m.group(1), m.group(2).lower()
        try:
            if ipaddress.ip_address(nip).version != 4:
                continue
        except ValueError:
            continue
        if MAC_RE.fullmatch(mac):
            neigh_by_mac[mac] = nip

    lease_by_mac: Dict[str, Dict[str, str]] = {}
    for raw in _section(out, "LEASES").splitlines():
        parts = raw.strip().split()
        if len(parts) < 4:
            continue
        mac = parts[1].lower()
        if not MAC_RE.fullmatch(mac):
            continue
        lease_ip = parts[2]
        hostname = "" if parts[3] in {"*", "-"} else parts[3]
        lease_by_mac[mac] = {"ip": lease_ip, "hostname": hostname}

    snapshot_by_mac, snapshot_by_ip = _snapshot_clients()
    devices: List[Dict[str, str]] = []
    for mac in sorted(fdb_macs):
        lease = lease_by_mac.get(mac, {})
        snap = snapshot_by_mac.get(mac, {})
        device_ip = neigh_by_mac.get(mac) or lease.get("ip", "") or snap.get("ip", "")
        hostname = snap.get("hostname", "") or lease.get("hostname", "")
        if device_ip and not hostname:
            hostname = snapshot_by_ip.get(device_ip, {}).get("hostname", "")
        if device_ip in SPECIAL_NAMES:
            hostname = SPECIAL_NAMES[device_ip]
        devices.append({
            "ip": device_ip,
            "hostname": hostname,
            "mac": mac,
        })

    devices.sort(key=lambda row: (_ip_sort(row.get("ip", "")), row.get("hostname", ""), row.get("mac", "")))

    link_text = _section(out, "LINK")
    values: Dict[str, str] = {}
    for line in link_text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    carrier = values.get("CARRIER") == "1"
    speed = None
    try:
        raw_speed = int(values.get("SPEED") or 0)
        if raw_speed > 0:
            speed = raw_speed
    except ValueError:
        speed = None

    return {
        "ok": True,
        "version": VERSION,
        "router_ip": ip,
        "port": port,
        "up": carrier,
        "operstate": values.get("OPER") or "unknown",
        "speed_mbps": speed,
        "count": len(devices),
        "devices": devices,
    }


def init_lan_port_inspector_v630(app: Any) -> None:
    endpoint = "v630_lan_port_devices"
    if endpoint in app.view_functions:
        return

    @app.get("/api/v630/lan-port-devices", endpoint=endpoint)
    def _devices():
        try:
            result = inspect_port(
                str(request.args.get("ip") or ""),
                str(request.args.get("port") or ""),
            )
            return jsonify(result)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

from __future__ import annotations

import copy
import ipaddress
import re
import shlex
from typing import Any, Dict, List, Tuple

from flask import jsonify, request

from mesh_core import controller
from client_ip_resolver_v632 import resolve_client_ipv4

VERSION = "7.0.2"
MAC_RE = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$", re.I)
PORT_RE = re.compile(r"^lan([1-4])$", re.I)

SPECIAL_NAMES = {
    "192.168.30.186": "iHOST",
    "192.168.30.223": "HASSIO",
}


def _router_ips() -> set[str]:
    return {str(r.get("ip") or "") for r in controller.routers}


def _validate_ip(ip: str) -> str:
    ip = str(ip or "").strip()
    if ip not in _router_ips():
        raise ValueError("Neznámý router")
    return ip


def _section(text: str, name: str) -> str:
    m = re.search(rf"__{re.escape(name)}_BEGIN__\n(.*?)\n__{re.escape(name)}_END__", text, re.S)
    return m.group(1) if m else ""


def _valid_unicast_mac(mac: str) -> bool:
    mac = str(mac or "").lower().strip()
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


def _parse_leases(text: str) -> Dict[str, Dict[str, str]]:
    result: Dict[str, Dict[str, str]] = {}
    for raw in text.splitlines():
        parts = raw.strip().split()
        if len(parts) < 4:
            continue
        mac = parts[1].lower()
        if not MAC_RE.fullmatch(mac):
            continue
        hostname = "" if parts[3] in {"*", "-"} else parts[3]
        result[mac] = {"ip": parts[2], "hostname": hostname}
    return result


def _main_router_leases() -> Dict[str, Dict[str, str]]:
    client = None
    try:
        client = controller.ssh_client("192.168.30.1", timeout=4)
        out, _err, code = controller.command(client, "cat /tmp/dhcp.leases 2>/dev/null || true", timeout=8)
        if code == 0:
            return _parse_leases(out)
    except Exception:
        pass
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
    return {}


def _live_node(app: Any, ip: str) -> Dict[str, Any]:
    collector = app.extensions.get("live_topology_v503") if hasattr(app, "extensions") else None
    if collector is None:
        return {}
    try:
        with collector.lock:
            return copy.deepcopy(collector.nodes.get(ip) or {})
    except Exception:
        return {}


def _router_tables(ip: str) -> str:
    command = r'''printf '__FDB_BEGIN__\n'
if command -v bridge >/dev/null 2>&1; then
  bridge fdb show br br-lan 2>/dev/null || bridge fdb show 2>/dev/null || true
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
        return out
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def inspect_node(app: Any, ip: str) -> Dict[str, Any]:
    ip = _validate_ip(ip)
    node = _live_node(app, ip)
    if node and not node.get("online"):
        return {
            "ok": True,
            "version": VERSION,
            "router_ip": ip,
            "router_name": node.get("name") or node.get("hostname") or ip,
            "online": False,
            "count": 0,
            "groups": [],
        }

    text = _router_tables(ip)
    local_macs = {
        line.strip().lower()
        for line in _section(text, "LOCAL").splitlines()
        if MAC_RE.fullmatch(line.strip())
    }

    lan_by_port: Dict[str, set[str]] = {f"lan{i}": set() for i in range(1, 5)}
    for raw in _section(text, "FDB").splitlines():
        m = re.match(r"^([0-9a-f:]{17})\s+dev\s+(lan[1-4])\b", raw.strip(), re.I)
        if not m:
            continue
        mac, port = m.group(1).lower(), m.group(2).lower()
        low = {p.lower() for p in raw.split()[3:]}
        if not _valid_unicast_mac(mac) or mac in local_macs:
            continue
        if "self" in low or "permanent" in low or "local" in low:
            continue
        lan_by_port[port].add(mac)

    neigh_by_mac: Dict[str, str] = {}
    for raw in _section(text, "NEIGH").splitlines():
        m = re.match(r"^(\S+)\s+dev\s+\S+.*?\slladdr\s+([0-9a-f:]{17})\b", raw.strip(), re.I)
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

    lease_by_mac = _parse_leases(_section(text, "LEASES"))
    if ip != "192.168.30.1":
        for mac, row in _main_router_leases().items():
            lease_by_mac.setdefault(mac, row)

    snapshot_by_mac, snapshot_by_ip = _snapshot_clients()

    wifi5 = {
        str(mac).lower() for mac in (node.get("wifi_client_macs_5") or [])
        if MAC_RE.fullmatch(str(mac).lower())
    }
    wifi24 = {
        str(mac).lower() for mac in (node.get("wifi_client_macs_24") or [])
        if MAC_RE.fullmatch(str(mac).lower())
    }
    # Při krátkém roaming/cache překryvu zobraz jednu MAC jen jednou; 5 GHz má prioritu.
    wifi24.difference_update(wifi5)
    for port in lan_by_port:
        lan_by_port[port].difference_update(wifi5)
        lan_by_port[port].difference_update(wifi24)

    # v6.3.2 active MAC -> IPv4 resolution
    all_client_macs: set[str] = set(wifi5) | set(wifi24)
    for _macs in lan_by_port.values():
        all_client_macs.update(_macs)
    unresolved_macs = {
        mac for mac in all_client_macs
        if not (
            neigh_by_mac.get(mac)
            or lease_by_mac.get(mac, {}).get("ip", "")
            or snapshot_by_mac.get(mac, {}).get("ip", "")
        )
    }
    resolved_ipv4 = resolve_client_ipv4(unresolved_macs) if unresolved_macs else {}

    def device(mac: str) -> Dict[str, str]:
        lease = lease_by_mac.get(mac, {})
        snap = snapshot_by_mac.get(mac, {})
        dip = neigh_by_mac.get(mac) or lease.get("ip", "") or snap.get("ip", "") or resolved_ipv4.get(mac, "")
        hostname = snap.get("hostname", "") or lease.get("hostname", "")
        if dip and not hostname:
            hostname = snapshot_by_ip.get(dip, {}).get("hostname", "")
        if dip in SPECIAL_NAMES:
            hostname = SPECIAL_NAMES[dip]
        return {"ip": dip, "hostname": hostname, "mac": mac}

    def rows(macs: set[str]) -> List[Dict[str, str]]:
        result = [device(mac) for mac in macs]
        result.sort(key=lambda row: (_ip_sort(row.get("ip", "")), row.get("hostname", ""), row.get("mac", "")))
        return result

    groups: List[Dict[str, Any]] = []
    group_defs = [
        ("wifi5", "Wi-Fi 5 GHz", wifi5),
        ("wifi24", "Wi-Fi 2.4 GHz", wifi24),
        ("lan1", "LAN1", lan_by_port["lan1"]),
        ("lan2", "LAN2", lan_by_port["lan2"]),
        ("lan3", "LAN3", lan_by_port["lan3"]),
        ("lan4", "LAN4", lan_by_port["lan4"]),
    ]
    for key, label, macs in group_defs:
        group_rows = rows(macs)
        if group_rows:
            groups.append({"key": key, "label": label, "count": len(group_rows), "devices": group_rows})

    count = sum(int(group.get("count") or 0) for group in groups)
    return {
        "ok": True,
        "version": VERSION,
        "router_ip": ip,
        "router_name": node.get("name") or node.get("hostname") or ip,
        "online": bool(node.get("online", True)),
        "count": count,
        "groups": groups,
    }


def init_topology_inspector_v631(app: Any) -> None:
    endpoint = "v631_topology_node_devices"
    if endpoint in app.view_functions:
        return

    @app.get("/api/v631/topology-node-devices", endpoint=endpoint)
    def _devices():
        try:
            return jsonify(inspect_node(app, str(request.args.get("ip") or "")))
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

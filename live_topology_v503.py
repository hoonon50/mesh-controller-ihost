from __future__ import annotations

import copy
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import paramiko
from flask import jsonify

VERSION = "5.0.3"
ROUTERS: List[Tuple[str, str]] = [
    ("192.168.30.1", "ROUTER"),
    ("192.168.30.2", "MESH1"),
    ("192.168.30.3", "MESH2"),
    ("192.168.30.4", "MESH3"),
    ("192.168.30.5", "MESH4"),
]
SSH_USER = os.environ.get("MESH_SSH_USER", "root")
SSH_PASS = os.environ.get("MESH_SSH_PASS", "root")
SSH_TIMEOUT = max(2, int(os.environ.get("MESH_SSH_TIMEOUT", "6")))
POLL_SECONDS = max(3, int(os.environ.get("MESH_LIVE_TOPOLOGY_POLL", "5")))
HEALTH_SECONDS = max(POLL_SECONDS, int(os.environ.get("MESH_LIVE_HEALTH_POLL", "15")))

try:
    LOCAL_TZ = ZoneInfo(os.environ.get("TZ", "Europe/Prague"))
except Exception:
    LOCAL_TZ = ZoneInfo("UTC")

MAC_RE = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$", re.I)


def _now_text() -> str:
    return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _clock_text() -> str:
    return datetime.now(LOCAL_TZ).strftime("%H:%M:%S")


def _format_uptime(seconds: Any) -> str:
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return "—"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    return f"{hours}h {minutes}m"


def _parse_bitrate_mbps(text: str) -> Optional[float]:
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*MBit/s", text or "", re.I)
    if not m:
        m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*Mbit/s", text or "", re.I)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _station_records(text: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"^Station\s+([0-9a-f:]{17})\b", line, re.I)
        if m:
            if current:
                rows.append(current)
            current = {"mac": m.group(1).lower(), "signal": None, "tx": "", "rx": ""}
            continue
        if current is None:
            continue
        m = re.match(r"^signal:\s*(-?\d+)", line)
        if m:
            current["signal"] = int(m.group(1))
            continue
        m = re.match(r"^signal avg:\s*(-?\d+)", line)
        if m and current.get("signal") is None:
            current["signal"] = int(m.group(1))
            continue
        m = re.match(r"^tx bitrate:\s*(.+)$", line, re.I)
        if m:
            current["tx"] = m.group(1).strip()
            continue
        m = re.match(r"^rx bitrate:\s*(.+)$", line, re.I)
        if m:
            current["rx"] = m.group(1).strip()
    if current:
        rows.append(current)
    return rows


def _iface_type(info: str) -> str:
    m = re.search(r"(?m)^\s*type\s+(.+?)\s*$", info)
    return (m.group(1).strip().lower() if m else "")


def _iface_mac(info: str) -> str:
    m = re.search(r"(?m)^\s*addr\s+([0-9a-f:]{17})\s*$", info, re.I)
    return m.group(1).lower() if m else ""


def _iface_band(info: str) -> str:
    m = re.search(r"channel\s+\d+\s+\((\d+)\s+MHz\)", info, re.I)
    if not m:
        return "?"
    freq = int(m.group(1))
    if 2400 <= freq < 3000:
        return "2.4"
    if 4900 <= freq < 5925:
        return "5"
    if freq >= 5925:
        return "6"
    return "?"


def _ethernet_fdb_macs(text: str, wireless_ifnames: set[str]) -> set[str]:
    result: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"^([0-9a-f:]{17})\s+dev\s+(\S+)", line, re.I)
        if not m:
            continue
        mac, dev = m.group(1).lower(), m.group(2)
        low = line.lower().split()
        if not MAC_RE.match(mac) or any(flag in low for flag in ("self", "permanent", "local")):
            continue
        if dev in wireless_ifnames:
            continue
        d = dev.lower()
        if d.startswith(("wan", "wwan", "pppoe", "br-", "mesh", "wlan", "phy", "bat", "docker", "veth")):
            continue
        # Cudy/DSA typicky lan1/lan2; ethX zachováme jako fallback pro starší targety.
        if d.startswith(("lan", "eth")):
            result.add(mac)
    return result


class LiveTopologyCollector:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.sequence = 0
        self.health_publish_monotonic = 0.0
        self.nodes: Dict[str, Dict[str, Any]] = {
            ip: {
                "ip": ip,
                "name": name,
                "hostname": name,
                "online": False,
                "clients": 0,
                "clients_24": 0,
                "clients_5": 0,
                "lan_clients": 0,
                "cpu_c": None,
                "uptime_seconds": None,
                "uptime": "—",
                "mesh_ifaces": [],
                "mesh_peers": [],
                "wifi_client_macs_24": [],
                "wifi_client_macs_5": [],
                "lan_client_macs": [],
                "error": "čekám na první vzorek",
                "updated_at": "",
            }
            for ip, name in ROUTERS
        }
        self.links: List[Dict[str, Any]] = []
        self.updated_at = ""
        self.last_duration_ms = 0
        self._health_cache: Dict[str, Dict[str, Any]] = {}

    def _connect(self, ip: str) -> paramiko.SSHClient:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: Dict[str, Any] = {
            "hostname": ip,
            "username": SSH_USER,
            "timeout": SSH_TIMEOUT,
            "banner_timeout": SSH_TIMEOUT,
            "auth_timeout": SSH_TIMEOUT,
        }
        if SSH_PASS:
            kwargs.update({"password": SSH_PASS, "look_for_keys": False, "allow_agent": False})
        ssh.connect(**kwargs)
        return ssh

    def _fetch_node(self, ip: str, name: str) -> Dict[str, Any]:
        command = r'''set -u
printf '__SYS_BEGIN__\n'
printf 'HOSTNAME=%s\n' "$(uci -q get system.@system[0].hostname || hostname 2>/dev/null || true)"
printf 'UPTIME=%s\n' "$(cut -d' ' -f1 /proc/uptime 2>/dev/null || true)"
TEMP=''
for f in /sys/class/thermal/thermal_zone*/temp /sys/class/hwmon/hwmon*/temp*_input; do
  [ -r "$f" ] || continue
  v="$(cat "$f" 2>/dev/null || true)"
  case "$v" in ''|*[!0-9-]*) continue;; esac
  if [ "$v" -gt 1000 ] 2>/dev/null; then v=$((v / 1000)); fi
  if [ "$v" -gt 0 ] 2>/dev/null && [ "$v" -lt 150 ] 2>/dev/null; then TEMP="$v"; break; fi
done
printf 'TEMP=%s\n' "$TEMP"
printf '__SYS_END__\n'

for IF in $(iw dev 2>/dev/null | awk '$1=="Interface" {print $2}'); do
  printf '__IFACE_BEGIN__ %s\n' "$IF"
  iw dev "$IF" info 2>/dev/null || true
  printf '__STATIONS_BEGIN__\n'
  iw dev "$IF" station dump 2>/dev/null || true
  printf '__STATIONS_END__\n'
  printf '__IFACE_END__\n'
done

printf '__FDB_BEGIN__\n'
if command -v bridge >/dev/null 2>&1; then
  bridge fdb show br br-lan 2>/dev/null || bridge fdb show 2>/dev/null || true
fi
printf '__FDB_END__\n'
'''
        ssh = self._connect(ip)
        try:
            _stdin, stdout, stderr = ssh.exec_command(command, timeout=12)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            rc = stdout.channel.recv_exit_status()
            if rc != 0:
                raise RuntimeError((err or out).strip() or f"SSH rc={rc}")
        finally:
            ssh.close()

        sys_match = re.search(r"__SYS_BEGIN__\n(.*?)__SYS_END__", out, re.S)
        sys_values: Dict[str, str] = {}
        if sys_match:
            for line in sys_match.group(1).splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    sys_values[key.strip()] = value.strip()

        ifaces: List[Dict[str, Any]] = []
        for m in re.finditer(r"__IFACE_BEGIN__\s+(\S+)\n(.*?)__IFACE_END__", out, re.S):
            ifname = m.group(1)
            body = m.group(2)
            parts = body.split("__STATIONS_BEGIN__", 1)
            info = parts[0]
            stations_text = ""
            if len(parts) == 2:
                stations_text = parts[1].split("__STATIONS_END__", 1)[0]
            ifaces.append({
                "ifname": ifname,
                "type": _iface_type(info),
                "mac": _iface_mac(info),
                "band": _iface_band(info),
                "stations": _station_records(stations_text),
            })

        wifi24: set[str] = set()
        wifi5: set[str] = set()
        mesh_ifaces: List[Dict[str, str]] = []
        mesh_peers: List[Dict[str, Any]] = []
        wireless_ifnames = {row["ifname"] for row in ifaces}

        for iface in ifaces:
            typ = iface["type"]
            stations = iface["stations"]
            if typ == "ap":
                target = wifi24 if iface["band"] == "2.4" else wifi5 if iface["band"] == "5" else None
                if target is not None:
                    target.update(row["mac"] for row in stations if MAC_RE.match(row["mac"]))
            elif "mesh" in typ:
                if iface["mac"]:
                    mesh_ifaces.append({"ifname": iface["ifname"], "mac": iface["mac"]})
                for row in stations:
                    mesh_peers.append({
                        "ifname": iface["ifname"],
                        "peer_mac": row["mac"],
                        "signal": row.get("signal"),
                        "tx": row.get("tx", ""),
                        "rx": row.get("rx", ""),
                    })

        fdb_match = re.search(r"__FDB_BEGIN__\n(.*?)__FDB_END__", out, re.S)
        lan_macs = _ethernet_fdb_macs(fdb_match.group(1) if fdb_match else "", wireless_ifnames)
        # Pokud stejnou MAC současně vidíme přes AP, LAN fallback ji nesmí zdvojit.
        lan_macs.difference_update(wifi24)
        lan_macs.difference_update(wifi5)

        try:
            uptime_s: Optional[int] = int(float(sys_values.get("UPTIME", "")))
        except (TypeError, ValueError):
            uptime_s = None
        try:
            cpu: Optional[int] = int(sys_values.get("TEMP", "")) if sys_values.get("TEMP", "") else None
        except ValueError:
            cpu = None

        all_clients = wifi24 | wifi5 | lan_macs
        return {
            "ip": ip,
            "name": name,
            "hostname": sys_values.get("HOSTNAME") or name,
            "online": True,
            "clients": len(all_clients),
            "clients_24": len(wifi24),
            "clients_5": len(wifi5),
            "lan_clients": len(lan_macs),
            "cpu_c": cpu,
            "uptime_seconds": uptime_s,
            "uptime": _format_uptime(uptime_s),
            "mesh_ifaces": mesh_ifaces,
            "mesh_peers": mesh_peers,
            "wifi_client_macs_24": sorted(wifi24),
            "wifi_client_macs_5": sorted(wifi5),
            "lan_client_macs": sorted(lan_macs),
            "error": "",
            "updated_at": _now_text(),
        }

    @staticmethod
    def _build_links(nodes: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        mac_to_ip: Dict[str, str] = {}
        for ip, node in nodes.items():
            if not node.get("online"):
                continue
            for iface in node.get("mesh_ifaces", []):
                mac = str(iface.get("mac") or "").lower()
                if MAC_RE.match(mac):
                    mac_to_ip[mac] = ip

        acc: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for source_ip, node in nodes.items():
            if not node.get("online"):
                continue
            for peer in node.get("mesh_peers", []):
                target_ip = mac_to_ip.get(str(peer.get("peer_mac") or "").lower())
                if not target_ip or target_ip == source_ip:
                    continue
                a, b = sorted((source_ip, target_ip), key=lambda x: int(x.rsplit(".", 1)[-1]))
                row = acc.setdefault((a, b), {"a": a, "b": b, "signals": [], "speeds": []})
                sig = peer.get("signal")
                if isinstance(sig, int):
                    row["signals"].append(sig)
                for key in ("tx", "rx"):
                    speed = _parse_bitrate_mbps(str(peer.get(key) or ""))
                    if speed is not None:
                        row["speeds"].append(speed)

        links: List[Dict[str, Any]] = []
        for key in sorted(acc, key=lambda p: (int(p[0].rsplit('.',1)[-1]), int(p[1].rsplit('.',1)[-1]))):
            row = acc[key]
            signals = row["signals"]
            speeds = row["speeds"]
            signal = round(sum(signals) / len(signals)) if signals else None
            speed = max(speeds) if speeds else None
            links.append({
                "a": row["a"],
                "b": row["b"],
                "signal_dbm": signal,
                "speed_mbps": round(speed, 1) if speed is not None else None,
            })
        return links

    def sample(self) -> None:
        started = time.monotonic()
        fetched: Dict[str, Dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=len(ROUTERS), thread_name_prefix="v503-live") as pool:
            futures = {pool.submit(self._fetch_node, ip, name): (ip, name) for ip, name in ROUTERS}
            for future in as_completed(futures):
                ip, name = futures[future]
                try:
                    fetched[ip] = future.result()
                except Exception as exc:
                    old = copy.deepcopy(self.nodes.get(ip, {}))
                    fetched[ip] = {
                        **old,
                        "ip": ip,
                        "name": name,
                        "hostname": old.get("hostname") or name,
                        "online": False,
                        "clients": 0,
                        "clients_24": 0,
                        "clients_5": 0,
                        "lan_clients": 0,
                        "mesh_ifaces": [],
                        "mesh_peers": [],
                        "wifi_client_macs_24": [],
                        "wifi_client_macs_5": [],
                        "lan_client_macs": [],
                        "error": str(exc),
                        "updated_at": _now_text(),
                    }

        # CPU/uptime publikujeme nejvýše každých HEALTH_SECONDS. Samotné SSH je už
        # otevřené kvůli topologii, takže to nepřidává další spojení na router.
        now_mono = time.monotonic()
        publish_health = (now_mono - self.health_publish_monotonic) >= HEALTH_SECONDS
        if publish_health:
            self.health_publish_monotonic = now_mono
            for ip, node in fetched.items():
                if node.get("online"):
                    self._health_cache[ip] = {
                        "cpu_c": node.get("cpu_c"),
                        "uptime_seconds": node.get("uptime_seconds"),
                        "uptime": node.get("uptime"),
                    }
        for ip, node in fetched.items():
            cached = self._health_cache.get(ip)
            if cached:
                node.update(cached)
            elif not node.get("online"):
                node.update({"cpu_c": None, "uptime_seconds": None, "uptime": "—"})

        links = self._build_links(fetched)
        with self.lock:
            self.nodes = fetched
            self.links = links
            self.sequence += 1
            self.updated_at = _now_text()
            self.last_duration_ms = int((time.monotonic() - started) * 1000)

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            nodes = copy.deepcopy(self.nodes)
            links = copy.deepcopy(self.links)
            online = sum(1 for node in nodes.values() if node.get("online"))

            # Globální klienti jsou unikátní MAC napříč uzly.
            mac24: set[str] = set()
            mac5: set[str] = set()
            lan: set[str] = set()
            for node in nodes.values():
                if not node.get("online"):
                    continue
                mac24.update(node.get("wifi_client_macs_24", []))
                mac5.update(node.get("wifi_client_macs_5", []))
                lan.update(node.get("lan_client_macs", []))
            lan.difference_update(mac24)
            lan.difference_update(mac5)
            all_clients = mac24 | mac5 | lan

            public_nodes = []
            for ip, _name in ROUTERS:
                n = copy.deepcopy(nodes[ip])
                # Interní seznamy MAC nejsou potřeba v browseru.
                for key in ("mesh_ifaces", "mesh_peers", "wifi_client_macs_24", "wifi_client_macs_5", "lan_client_macs"):
                    n.pop(key, None)
                public_nodes.append(n)

            return {
                "ok": online > 0,
                "version": VERSION,
                "sequence": self.sequence,
                "updated_at": self.updated_at,
                "clock": _clock_text(),
                "poll_seconds": POLL_SECONDS,
                "health_seconds": HEALTH_SECONDS,
                "sample_duration_ms": self.last_duration_ms,
                "summary": {
                    "online_routers": online,
                    "router_count": len(ROUTERS),
                    "mesh_links": len(links),
                    "clients": len(all_clients),
                    "clients_24": len(mac24),
                    "clients_5": len(mac5),
                    "lan_clients": len(lan),
                },
                "nodes": public_nodes,
                "links": links,
            }

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            start = time.monotonic()
            try:
                self.sample()
            except Exception:
                pass
            elapsed = time.monotonic() - start
            self.stop_event.wait(max(0.25, POLL_SECONDS - elapsed))

    def start(self) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._loop, name="mesh-v503-live-topology", daemon=True)
            self.thread.start()


_collector: Optional[LiveTopologyCollector] = None


def init_live_topology_v503(app: Any) -> LiveTopologyCollector:
    global _collector
    existing = app.extensions.get("live_topology_v503") if hasattr(app, "extensions") else None
    if existing is not None:
        return existing
    if _collector is None:
        _collector = LiveTopologyCollector()
    collector = _collector
    app.extensions["live_topology_v503"] = collector

    if "v503_live_topology" not in app.view_functions:
        @app.get("/api/v503/live-topology", endpoint="v503_live_topology")
        def _api_live_topology():
            return jsonify(collector.snapshot())

    collector.start()
    return collector

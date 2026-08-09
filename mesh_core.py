from __future__ import annotations

import csv
import ipaddress
import json
import os
import re
import shlex
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import paramiko

DATA_DIR = Path(os.getenv("MESH_DATA_DIR", "/data"))
CONFIG_FILE = DATA_DIR / "config.json"
UPLINK_FILE = DATA_DIR / "mesh_uplink_ports.json"
BACKUP_DIR = DATA_DIR / "backups"
LOG_FILE = DATA_DIR / "mesh-controller.log"

DEFAULT_CONFIG: Dict[str, Any] = {
    "routers": [
        {"ip": "192.168.30.1", "name": "Hlavní Node (.1)"},
        {"ip": "192.168.30.2", "name": "Uzel 2 (.2)"},
        {"ip": "192.168.30.3", "name": "Uzel 3 (.3)"},
        {"ip": "192.168.30.4", "name": "Uzel 4 (.4)"},
        {"ip": "192.168.30.5", "name": "Uzel 5 (.5)"},
    ],
    "main_node": "192.168.30.1",
    "ssh_user": "root",
    "ssh_password": "root",
    "ssh_key_file": "",
    "ssh_timeout": 4,
    "command_timeout": 15,
    "lan_network": "192.168.30.0/24",
    "lan_bridge": "br-lan",
    "refresh_seconds": 30,
}

MAC_RE = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$", re.I)
IFACE_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")


@dataclass
class Station:
    mac: str
    signal: Optional[int] = None
    signal_avg: Optional[int] = None
    tx_bitrate: str = ""
    rx_bitrate: str = ""
    inactive_ms: Optional[int] = None
    connected_seconds: Optional[int] = None


@dataclass
class WirelessInterface:
    ifname: str
    mode: str
    ssid: str
    radio: str
    band: str
    section: str = ""
    mac: str = ""


@dataclass
class Client:
    node_ip: str
    node_name: str
    mac: str
    interface: str
    ssid: str
    band: str
    signal: Optional[int]
    tx_bitrate: str = ""
    rx_bitrate: str = ""
    ip: str = ""
    hostname: str = ""
    connection_type: str = "Wi-Fi"
    port: str = ""
    bridge: str = ""
    link_speed: str = ""
    detection_source: str = ""
    neighbor_state: str = ""
    verification: str = ""


@dataclass
class NeighborEntry:
    node_ip: str
    node_name: str
    ip: str
    mac: str
    dev: str
    state: str


@dataclass
class LanObservation:
    node_ip: str
    node_name: str
    mac: str
    port: str
    bridge: str
    link_speed: str = ""
    detection_source: str = "FDB"


@dataclass
class LanPortStatus:
    node_ip: str
    node_name: str
    port: str
    bridge: str
    port_no: Optional[int] = None
    operstate: str = "unknown"
    carrier: bool = False
    speed: str = ""
    client_macs: Set[str] = field(default_factory=set)
    is_uplink: bool = False

    @property
    def connected(self) -> bool:
        return self.carrier or self.operstate.lower() == "up" or bool(self.client_macs)


@dataclass
class MeshPeer:
    source_ip: str
    source_ifname: str
    peer_mac: str
    signal: Optional[int]
    tx_bitrate: str = ""
    rx_bitrate: str = ""


@dataclass
class NodeResult:
    ip: str
    name: str
    online: bool = False
    error: str = ""
    hostname: str = ""
    uptime: str = ""
    load: str = ""
    interfaces: List[WirelessInterface] = field(default_factory=list)
    clients: List[Client] = field(default_factory=list)
    lan_observations: List[LanObservation] = field(default_factory=list)
    lan_ports: List[LanPortStatus] = field(default_factory=list)
    mesh_peers: List[MeshPeer] = field(default_factory=list)
    mesh_macs: Set[str] = field(default_factory=set)
    local_macs: Set[str] = field(default_factory=set)
    leases: Dict[str, Dict[str, str]] = field(default_factory=dict)
    neighbors: Dict[str, str] = field(default_factory=dict)
    neighbor_entries: List[NeighborEntry] = field(default_factory=list)
    lan_detection_notes: List[str] = field(default_factory=list)
    uci_wireless: str = ""


@dataclass
class MeshLink:
    a_ip: str
    b_ip: str
    signals: List[int] = field(default_factory=list)
    tx_rates: List[str] = field(default_factory=list)
    rx_rates: List[str] = field(default_factory=list)

    @property
    def signal(self) -> Optional[int]:
        if not self.signals:
            return None
        return round(sum(self.signals) / len(self.signals))

    @property
    def label(self) -> str:
        parts: List[str] = []
        if self.signal is not None:
            parts.append(f"{self.signal} dBm")
        rates = [rate for rate in self.tx_rates if rate]
        if rates:
            parts.append(rates[0])
        return " · ".join(parts) if parts else "mesh"


def normalize_mac(value: str) -> str:
    return value.strip().lower()


def parse_station_dump(output: str) -> List[Station]:
    stations: List[Station] = []
    current: Optional[Station] = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        match = re.match(r"^Station\s+([0-9a-f:]{17})\b", line, re.I)
        if match:
            if current is not None:
                stations.append(current)
            current = Station(mac=normalize_mac(match.group(1)))
            continue
        if current is None:
            continue
        match = re.match(r"^signal:\s*(-?\d+)", line)
        if match:
            current.signal = int(match.group(1)); continue
        match = re.match(r"^signal avg:\s*(-?\d+)", line)
        if match:
            current.signal_avg = int(match.group(1)); continue
        match = re.match(r"^tx bitrate:\s*(.+)$", line)
        if match:
            current.tx_bitrate = match.group(1).strip(); continue
        match = re.match(r"^rx bitrate:\s*(.+)$", line)
        if match:
            current.rx_bitrate = match.group(1).strip(); continue
        match = re.match(r"^inactive time:\s*(\d+)\s*ms", line)
        if match:
            current.inactive_ms = int(match.group(1)); continue
        match = re.match(r"^connected time:\s*(\d+)\s*seconds", line)
        if match:
            current.connected_seconds = int(match.group(1))
    if current is not None:
        stations.append(current)
    return stations


def parse_dhcp_leases(output: str, lan_network: ipaddress.IPv4Network) -> Dict[str, Dict[str, str]]:
    leases: Dict[str, Dict[str, str]] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        _expiry, mac, ip, hostname = parts[:4]
        mac = normalize_mac(mac)
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if address.version != 4 or address not in lan_network or address in {lan_network.network_address, lan_network.broadcast_address}:
            continue
        if MAC_RE.fullmatch(mac):
            leases[mac] = {"ip": ip, "hostname": "" if hostname == "*" else hostname}
    return leases


def is_valid_lan_ipv4(value: str, lan_network: ipaddress.IPv4Network) -> bool:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    if address.version != 4 or address not in lan_network:
        return False
    return address not in {lan_network.network_address, lan_network.broadcast_address}


def parse_ip_neighbors(output: str, lan_bridge: str, lan_network: ipaddress.IPv4Network) -> Dict[str, str]:
    neighbors: Dict[str, str] = {}
    for line in output.splitlines():
        match = re.search(r"^(\S+)\s+dev\s+(\S+).*?\blladdr\s+([0-9a-f:]{17})\b", line, re.I)
        if match:
            ip, dev, mac = match.groups()
            if dev == lan_bridge and is_valid_lan_ipv4(ip, lan_network):
                neighbors[normalize_mac(mac)] = ip
    return neighbors


def parse_ip_neighbor_entries(output: str, node_ip: str, node_name: str, lan_bridge: str, lan_network: ipaddress.IPv4Network) -> List[NeighborEntry]:
    entries: List[NeighborEntry] = []
    ignored_states = {"FAILED", "INCOMPLETE", "NOARP", "NONE"}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        match = re.search(r"^(\S+)\s+dev\s+(\S+).*?\blladdr\s+([0-9a-f:]{17})\b(?:.*?\s([A-Z]+))?$", line, re.I)
        if not match:
            continue
        ip, dev, mac, state = match.groups()
        mac = normalize_mac(mac)
        state = (state or "UNKNOWN").upper()
        if not is_valid_lan_ipv4(ip, lan_network) or dev != lan_bridge:
            continue
        if not MAC_RE.fullmatch(mac) or not is_unicast_mac(mac) or state in ignored_states:
            continue
        entries.append(NeighborEntry(node_ip=node_ip, node_name=node_name, ip=ip, mac=mac, dev=dev, state=state))
    return entries


def parse_interface_macs(output: str) -> Set[str]:
    found: Set[str] = set()
    for token in output.split():
        mac = normalize_mac(token)
        if MAC_RE.fullmatch(mac):
            found.add(mac)
    return found


def parse_port_number(value: str) -> Optional[int]:
    raw = value.strip().lower()
    if not raw:
        return None
    try:
        return int(raw, 0)
    except ValueError:
        try:
            return int(raw, 16)
        except ValueError:
            return None


def parse_bridge_ports(output: str) -> Dict[str, Dict[str, Any]]:
    ports: Dict[str, Dict[str, Any]] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            parts = line.split()
        if len(parts) < 2:
            continue
        bridge, port = parts[0].strip(), parts[1].strip()
        speed = parts[2].strip() if len(parts) > 2 else ""
        port_no = parse_port_number(parts[3]) if len(parts) > 3 else None
        operstate = parts[4].strip().lower() if len(parts) > 4 else "unknown"
        carrier_raw = parts[5].strip() if len(parts) > 5 else "0"
        if speed in {"-1", "0", "unknown"}:
            speed = ""
        elif speed.isdigit():
            speed = f"{speed} Mbit/s"
        ports[port] = {"bridge": bridge, "speed": speed, "port_no": port_no, "operstate": operstate, "carrier": carrier_raw == "1"}
    return ports


def parse_brctl_showmacs(output: str, port_number_to_name: Dict[int, str]) -> List[Tuple[str, str]]:
    entries: List[Tuple[str, str]] = []
    for raw_line in output.splitlines():
        match = re.match(r"^(\d+)\s+([0-9a-f:]{17})\s+(yes|no)\s+", raw_line.strip(), re.I)
        if not match:
            continue
        port_no_raw, mac, is_local = match.groups()
        if is_local.lower() == "yes":
            continue
        mac = normalize_mac(mac)
        port = port_number_to_name.get(int(port_no_raw))
        if port and MAC_RE.fullmatch(mac) and is_unicast_mac(mac):
            entries.append((mac, port))
    return entries


def is_unicast_mac(mac: str) -> bool:
    try:
        return not (int(mac.split(":", 1)[0], 16) & 1)
    except (ValueError, IndexError):
        return False


def parse_bridge_fdb(output: str) -> List[Tuple[str, str]]:
    entries: List[Tuple[str, str]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        match = re.match(r"^([0-9a-f:]{17})\s+dev\s+(\S+)", line, re.I)
        if not match:
            continue
        mac, port = normalize_mac(match.group(1)), match.group(2)
        flags = set(line.lower().split())
        if not MAC_RE.fullmatch(mac) or not is_unicast_mac(mac) or flags.intersection({"self", "permanent", "local"}):
            continue
        entries.append((mac, port))
    return entries


def is_probable_ethernet_port(port: str, wireless_ifnames: Set[str]) -> bool:
    name = port.lower()
    if port in wireless_ifnames:
        return False
    excluded_prefixes = ("br", "lo", "wlan", "phy", "mesh", "wds", "bat", "ifb", "veth", "docker", "podman", "tap", "tun", "gre", "gretap", "vxlan", "bond")
    return not name.startswith(excluded_prefixes)


def band_label(value: Any, radio: str = "") -> str:
    raw = str(value or "").lower()
    if "2g" in raw or "2.4" in raw:
        return "2,4 GHz"
    if "5g" in raw or raw == "5" or "5ghz" in raw:
        return "5 GHz"
    if "6g" in raw or raw == "6" or "6ghz" in raw:
        return "6 GHz"
    if radio == "radio0":
        return "2,4 GHz"
    if radio == "radio1":
        return "5 GHz"
    return raw or "?"


def parse_wireless_status(payload: str) -> List[WirelessInterface]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []
    interfaces: List[WirelessInterface] = []
    for radio, radio_data in data.items():
        if not isinstance(radio_data, dict):
            continue
        radio_cfg = radio_data.get("config") or {}
        band = band_label(radio_cfg.get("band") or radio_cfg.get("hwmode"), radio)
        for iface in radio_data.get("interfaces") or []:
            if not isinstance(iface, dict):
                continue
            cfg = iface.get("config") or {}
            ifname = str(iface.get("ifname") or "").strip()
            mode = str(cfg.get("mode") or "").strip().lower()
            ssid = str(cfg.get("ssid") or cfg.get("mesh_id") or "").strip()
            section = str(iface.get("section") or cfg.get("section") or "").strip()
            if ifname and mode:
                interfaces.append(WirelessInterface(ifname=ifname, mode=mode, ssid=ssid, radio=radio, band=band, section=section))
    return interfaces


def _jsonable(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(value)
    if hasattr(value, "__dataclass_fields__"):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


class MeshController:
    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        self.config = self._load_config()
        self.routers: List[Dict[str, str]] = self.config["routers"]
        self.main_node: str = self.config["main_node"]
        self.ssh_user: str = self.config["ssh_user"]
        self.ssh_password: str = self.config.get("ssh_password", "")
        self.ssh_key_file: str = self.config.get("ssh_key_file", "")
        self.ssh_timeout = int(self.config.get("ssh_timeout", 4))
        self.command_timeout = int(self.config.get("command_timeout", 15))
        self.lan_network = ipaddress.ip_network(self.config.get("lan_network", "192.168.30.0/24"))
        self.lan_bridge = self.config.get("lan_bridge", "br-lan")
        self.refresh_seconds = max(15, int(self.config.get("refresh_seconds", 30)))
        self.lan_uplink_ports = self._load_uplinks()
        self.node_results: Dict[str, NodeResult] = {}
        self.mesh_links: List[MeshLink] = []
        self.all_clients: List[Client] = []
        self.last_refresh = ""
        self.last_error = ""
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._logs: List[str] = []
        self.log("[START] OpenWrt Mesh Controller WEB spuštěn.")

    def _load_config(self) -> Dict[str, Any]:
        if not CONFIG_FILE.exists():
            CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
            return json.loads(json.dumps(DEFAULT_CONFIG))
        try:
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            loaded = {}
        merged = json.loads(json.dumps(DEFAULT_CONFIG))
        merged.update(loaded if isinstance(loaded, dict) else {})
        return merged

    def _load_uplinks(self) -> Dict[str, Set[str]]:
        defaults = {r["ip"]: set() for r in self.routers}
        if not UPLINK_FILE.exists():
            return defaults
        try:
            raw = json.loads(UPLINK_FILE.read_text(encoding="utf-8"))
            for ip in defaults:
                values = raw.get(ip, []) if isinstance(raw, dict) else []
                defaults[ip] = {str(v) for v in values}
        except Exception as exc:
            self.log(f"[WARN] Uplink konfiguraci nelze načíst: {exc}")
        return defaults

    def save_uplinks(self, mapping: Dict[str, List[str]]) -> None:
        cleaned = {r["ip"]: {str(p).strip() for p in mapping.get(r["ip"], []) if str(p).strip()} for r in self.routers}
        UPLINK_FILE.write_text(json.dumps({k: sorted(v) for k, v in cleaned.items()}, ensure_ascii=False, indent=2), encoding="utf-8")
        self.lan_uplink_ports = cleaned

    def log(self, message: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
        with self._lock:
            self._logs.append(line)
            self._logs = self._logs[-1000:]
        try:
            with LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def logs(self, limit: int = 250) -> List[str]:
        with self._lock:
            return self._logs[-max(1, min(limit, 1000)):]

    def make_ssh_client(self, ip: str, timeout: Optional[int] = None) -> paramiko.SSHClient:
        timeout = timeout or self.ssh_timeout
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: Dict[str, Any] = {"hostname": ip, "username": self.ssh_user, "timeout": timeout, "banner_timeout": timeout, "auth_timeout": timeout}
        if self.ssh_key_file:
            kwargs["key_filename"] = self.ssh_key_file
        if self.ssh_password:
            kwargs.update({"password": self.ssh_password, "look_for_keys": False, "allow_agent": False})
        else:
            kwargs.update({"look_for_keys": True, "allow_agent": True})
        ssh.connect(**kwargs)
        return ssh

    @staticmethod
    def ssh_command(ssh: paramiko.SSHClient, command: str, timeout: int = 15) -> Tuple[str, str, int]:
        _stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return out, err, stdout.channel.recv_exit_status()

    @staticmethod
    def ssh_script(ssh: paramiko.SSHClient, script: str, timeout: int = 45) -> Tuple[str, str, int]:
        stdin, stdout, stderr = ssh.exec_command("/bin/sh -s", timeout=timeout)
        stdin.write(script)
        if not script.endswith("\n"):
            stdin.write("\n")
        stdin.flush(); stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return out, err, stdout.channel.recv_exit_status()

    def discover_node(self, router: Dict[str, Any]) -> NodeResult:
        ip = router["ip"]
        result = NodeResult(ip=ip, name=router["name"])
        ssh: Optional[paramiko.SSHClient] = None
        try:
            ssh = self.make_ssh_client(ip)
            result.online = True
            out, _err, _code = self.ssh_command(ssh, "printf '%s\\n' \"$(uci -q get system.@system[0].hostname)\"; cut -d' ' -f1 /proc/uptime; cut -d' ' -f1-3 /proc/loadavg")
            info_lines = out.splitlines()
            if info_lines:
                result.hostname = info_lines[0].strip()
            if len(info_lines) > 1:
                try:
                    seconds = int(float(info_lines[1].strip())); days, rem = divmod(seconds, 86400); hours, rem = divmod(rem, 3600); minutes = rem // 60
                    result.uptime = f"{days}d {hours}h {minutes}m"
                except ValueError:
                    result.uptime = info_lines[1].strip()
            if len(info_lines) > 2:
                result.load = info_lines[2].strip()

            wireless_json, _e, _c = self.ssh_command(ssh, "ubus call network.wireless status 2>/dev/null || true")
            result.interfaces = parse_wireless_status(wireless_json)
            for iface in result.interfaces:
                qif = shlex.quote(iface.ifname)
                mac_out, _e, _c = self.ssh_command(ssh, f"cat /sys/class/net/{qif}/address 2>/dev/null || true")
                iface.mac = normalize_mac(mac_out.splitlines()[0]) if mac_out.strip() else ""
                station_out, _e, _c = self.ssh_command(ssh, f"iw dev {qif} station dump 2>/dev/null || true")
                stations = parse_station_dump(station_out)
                if iface.mode == "ap":
                    for st in stations:
                        result.clients.append(Client(node_ip=ip, node_name=result.name, mac=st.mac, interface=iface.ifname, ssid=iface.ssid, band=iface.band, signal=st.signal if st.signal is not None else st.signal_avg, tx_bitrate=st.tx_bitrate, rx_bitrate=st.rx_bitrate, connection_type="Wi-Fi", port=iface.ifname))
                elif iface.mode in {"mesh", "mesh_point", "mp"}:
                    if iface.mac and MAC_RE.fullmatch(iface.mac):
                        result.mesh_macs.add(iface.mac)
                    for st in stations:
                        result.mesh_peers.append(MeshPeer(source_ip=ip, source_ifname=iface.ifname, peer_mac=st.mac, signal=st.signal if st.signal is not None else st.signal_avg, tx_bitrate=st.tx_bitrate, rx_bitrate=st.rx_bitrate))

            local_macs_out, _e, _c = self.ssh_command(ssh, 'for f in /sys/class/net/*/address; do [ -r "$f" ] || continue; cat "$f"; done')
            result.local_macs = parse_interface_macs(local_macs_out)
            bridge_ports_out, _e, _c = self.ssh_command(ssh, 'for brif in /sys/class/net/*/brif; do [ -d "$brif" ] || continue; br=${brif%/brif}; br=${br##*/}; for path in "$brif"/*; do [ -e "$path" ] || continue; dev=${path##*/}; speed=$(cat "/sys/class/net/$dev/speed" 2>/dev/null); portno=$(cat "$path/port_no" 2>/dev/null); oper=$(cat "/sys/class/net/$dev/operstate" 2>/dev/null); carrier=$(cat "/sys/class/net/$dev/carrier" 2>/dev/null); printf "%s\\t%s\\t%s\\t%s\\t%s\\t%s\\n" "$br" "$dev" "$speed" "$portno" "$oper" "$carrier"; done; done')
            bridge_ports = parse_bridge_ports(bridge_ports_out)
            wireless_ifnames = {iface.ifname for iface in result.interfaces}
            excluded_uplinks = self.lan_uplink_ports.get(ip, set())
            for port, info in sorted(bridge_ports.items()):
                if info.get("bridge") != self.lan_bridge or port.lower().startswith(("wan", "pppoe", "wwan")) or not is_probable_ethernet_port(port, wireless_ifnames):
                    continue
                result.lan_ports.append(LanPortStatus(node_ip=ip, node_name=result.name, port=port, bridge=info.get("bridge", ""), port_no=info.get("port_no"), operstate=info.get("operstate", "unknown"), carrier=bool(info.get("carrier")), speed=info.get("speed", ""), is_uplink=port in excluded_uplinks))

            fdb_raw, fdb_err, fdb_code = self.ssh_command(ssh, f"if command -v bridge >/dev/null 2>&1; then echo __BRIDGE__; bridge fdb show 2>/dev/null; elif command -v brctl >/dev/null 2>&1; then echo __BRCTL__; brctl showmacs {shlex.quote(self.lan_bridge)} 2>/dev/null; else echo __NONE__; fi")
            fdb_lines = fdb_raw.splitlines(); method = fdb_lines[0].strip() if fdb_lines else "__NONE__"; payload = "\n".join(fdb_lines[1:])
            number_map = {int(info["port_no"]): p for p, info in bridge_ports.items() if info.get("port_no") is not None}
            if method == "__BRIDGE__":
                entries, source = parse_bridge_fdb(payload), "bridge FDB"
            elif method == "__BRCTL__":
                entries, source = parse_brctl_showmacs(payload, number_map), "brctl"
            else:
                entries, source = [], "bez FDB nástroje"; result.lan_detection_notes.append("Chybí bridge i brctl.")
            if fdb_code != 0:
                result.lan_detection_notes.append(f"Čtení FDB: {(fdb_err or 'chyba').strip()}")
            elif not entries:
                result.lan_detection_notes.append(f"{source}: žádná dynamická MAC.")
            status_by_name = {item.port: item for item in result.lan_ports}
            for mac, port in entries:
                info = bridge_ports.get(port)
                if not info or info.get("bridge") != self.lan_bridge or port in excluded_uplinks or port.lower().startswith(("wan", "pppoe", "wwan")) or not is_probable_ethernet_port(port, wireless_ifnames):
                    continue
                if port in status_by_name:
                    status_by_name[port].client_macs.add(mac)
                result.lan_observations.append(LanObservation(node_ip=ip, node_name=result.name, mac=mac, port=port, bridge=info.get("bridge", ""), link_speed=info.get("speed", ""), detection_source="FDB" if method == "__BRIDGE__" else "brctl"))

            leases_out, _e, _c = self.ssh_command(ssh, "cat /tmp/dhcp.leases 2>/dev/null || true")
            result.leases = parse_dhcp_leases(leases_out, self.lan_network)
            neigh_out, _e, _c = self.ssh_command(ssh, f"ip -4 neigh show dev {shlex.quote(self.lan_bridge)} 2>/dev/null || ip neigh show dev {shlex.quote(self.lan_bridge)} 2>/dev/null || true")
            result.neighbors = parse_ip_neighbors(neigh_out, self.lan_bridge, self.lan_network)
            result.neighbor_entries = parse_ip_neighbor_entries(neigh_out, ip, result.name, self.lan_bridge, self.lan_network)
            result.uci_wireless, _e, _c = self.ssh_command(ssh, "uci show wireless 2>/dev/null || true")
        except Exception as exc:
            result.online = False; result.error = str(exc)
        finally:
            if ssh is not None:
                ssh.close()
        return result

    def build_mesh_links(self, results: Dict[str, NodeResult]) -> List[MeshLink]:
        mesh_mac_to_ip: Dict[str, str] = {}
        for node in results.values():
            for mac in node.mesh_macs:
                mesh_mac_to_ip[mac] = node.ip
        links: Dict[Tuple[str, str], MeshLink] = {}
        for node in results.values():
            for peer in node.mesh_peers:
                peer_ip = mesh_mac_to_ip.get(peer.peer_mac)
                if not peer_ip or peer_ip == node.ip:
                    continue
                a_ip, b_ip = sorted((node.ip, peer_ip))
                key = (a_ip, b_ip)
                link = links.setdefault(key, MeshLink(a_ip=a_ip, b_ip=b_ip))
                if peer.signal is not None: link.signals.append(peer.signal)
                if peer.tx_bitrate: link.tx_rates.append(peer.tx_bitrate)
                if peer.rx_bitrate: link.rx_rates.append(peer.rx_bitrate)
        return list(links.values())

    def enrich_clients(self, results: Dict[str, NodeResult]) -> List[Client]:
        leases: Dict[str, Dict[str, str]] = {}; neighbors: Dict[str, str] = {}; local_macs: Set[str] = set(); mesh_macs: Set[str] = set()
        for node in results.values():
            leases.update(node.leases); neighbors.update(node.neighbors); local_macs.update(node.local_macs); mesh_macs.update(node.mesh_macs)
        clients: List[Client] = []; seen_wifi: Set[Tuple[str, str, str]] = set(); wifi_macs: Set[str] = set()
        for node in results.values():
            for c in node.clients:
                key = (c.node_ip, c.interface, c.mac)
                if key in seen_wifi: continue
                seen_wifi.add(key); wifi_macs.add(c.mac)
                lease = leases.get(c.mac, {}); c.ip = lease.get("ip") or neighbors.get(c.mac, ""); c.hostname = lease.get("hostname", ""); c.detection_source = "iw station"; c.verification = "Potvrzený Wi-Fi klient"; clients.append(c)
        lan_candidates: Dict[str, List[LanObservation]] = {}
        for node in results.values():
            for obs in node.lan_observations:
                if obs.mac in local_macs or obs.mac in mesh_macs or obs.mac in wifi_macs: continue
                lan_candidates.setdefault(obs.mac, []).append(obs)
        direct_lan_macs: Set[str] = set()
        for mac, observations in sorted(lan_candidates.items()):
            observations.sort(key=lambda item: (0 if item.port.lower().startswith(("lan", "eth")) else 1, item.node_ip, item.port)); selected = observations[0]; lease = leases.get(mac, {}); direct_lan_macs.add(mac)
            clients.append(Client(node_ip=selected.node_ip, node_name=selected.node_name, mac=mac, interface=selected.port, ssid="", band="Ethernet", signal=None, ip=lease.get("ip") or neighbors.get(mac, ""), hostname=lease.get("hostname", ""), connection_type="LAN", port=selected.port, bridge=selected.bridge, link_speed=selected.link_speed, detection_source=selected.detection_source, verification="Potvrzený LAN klient přes fyzický port"))
        state_priority = {"REACHABLE": 0, "DELAY": 1, "PROBE": 2, "STALE": 3, "PERMANENT": 4, "UNKNOWN": 5}; fallback: Dict[str, List[NeighborEntry]] = {}
        for node in results.values():
            wireless = {iface.ifname for iface in node.interfaces}
            for entry in node.neighbor_entries:
                if entry.mac in local_macs or entry.mac in mesh_macs or entry.mac in wifi_macs or entry.mac in direct_lan_macs or entry.dev in wireless: continue
                fallback.setdefault(entry.mac, []).append(entry)
        for mac, entries in sorted(fallback.items()):
            entries.sort(key=lambda e: (state_priority.get(e.state, 9), 0 if e.node_ip == self.main_node else 1, e.node_ip)); selected = entries[0]; lease = leases.get(mac, {})
            clients.append(Client(node_ip=selected.node_ip, node_name=selected.node_name, mac=mac, interface=selected.dev, ssid="", band="Ethernet", signal=None, ip=lease.get("ip") or selected.ip or neighbors.get(mac, ""), hostname=lease.get("hostname", ""), connection_type="Neurčené", port="Port nezjištěn", bridge=selected.dev, detection_source="ARP", neighbor_state=selected.state, verification="Pouze ARP – není potvrzený LAN port"))
        return clients

    def refresh(self) -> Dict[str, Any]:
        if not self._refresh_lock.acquire(blocking=False):
            return self.snapshot()
        try:
            self.log("[INFO] Zahajuji paralelní SSH diagnostiku všech uzlů…")
            results: Dict[str, NodeResult] = {}; lock = threading.Lock(); threads: List[threading.Thread] = []
            def worker(router: Dict[str, Any]) -> None:
                node = self.discover_node(router)
                with lock: results[node.ip] = node
                if node.online:
                    self.log(f"[OK] {node.ip}: Wi-Fi {len(node.clients)}, LAN porty {sum(p.connected for p in node.lan_ports)}/{len(node.lan_ports)}, mesh {len(node.mesh_peers)}")
                else:
                    self.log(f"[OFFLINE] {node.ip}: {node.error or 'SSH nedostupné'}")
            for router in self.routers:
                t = threading.Thread(target=worker, args=(router,), daemon=True); t.start(); threads.append(t)
            for t in threads: t.join()
            for router in self.routers:
                results.setdefault(router["ip"], NodeResult(ip=router["ip"], name=router["name"], online=False))
            links = self.build_mesh_links(results); clients = self.enrich_clients(results)
            with self._lock:
                self.node_results = results; self.mesh_links = links; self.all_clients = clients; self.last_refresh = time.strftime("%Y-%m-%d %H:%M:%S"); self.last_error = ""
            self.log(f"[HOTOVO] Online {sum(n.online for n in results.values())}/{len(self.routers)}, klienti {len(clients)}, mesh spoje {len(links)}.")
            return self.snapshot()
        except Exception as exc:
            self.last_error = str(exc); self.log(f"[KRITICKÁ CHYBA] {exc}"); raise
        finally:
            self._refresh_lock.release()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            nodes = {ip: _jsonable(node) for ip, node in self.node_results.items()}
            links = []
            for link in self.mesh_links:
                d = _jsonable(link); d["signal"] = link.signal; d["label"] = link.label; links.append(d)
            clients = [_jsonable(c) for c in self.all_clients]
            lease_macs: Set[str] = set()
            for node in self.node_results.values(): lease_macs.update(node.leases.keys())
            summary = {
                "online": sum(1 for n in self.node_results.values() if n.online), "total_nodes": len(self.routers), "clients": len(clients),
                "wifi": sum(c.connection_type == "Wi-Fi" for c in self.all_clients), "lan": sum(c.connection_type == "LAN" for c in self.all_clients), "unknown": sum(c.connection_type == "Neurčené" for c in self.all_clients),
                "mesh_links": len(self.mesh_links), "leases": len(lease_macs), "last_refresh": self.last_refresh, "last_error": self.last_error,
            }
            return {"summary": summary, "nodes": nodes, "links": links, "clients": clients, "routers": self.routers, "uplinks": {k: sorted(v) for k, v in self.lan_uplink_ports.items()}}

    def active_scan(self) -> Dict[str, Any]:
        self.log("[SCAN] Aktivní průzkum LAN…")
        prefix = str(self.lan_network.network_address).rsplit(".", 1)[0]
        def ping_ip(i: int) -> None:
            subprocess.run(["ping", "-c", "1", "-W", "1", f"{prefix}.{i}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
        workers = []
        for i in range(1, 255):
            t = threading.Thread(target=ping_ip, args=(i,), daemon=True); t.start(); workers.append(t)
            if len(workers) >= 40:
                for w in workers: w.join(); workers = []
        for w in workers: w.join()
        return self.refresh()

    def backup_configs(self) -> Dict[str, Any]:
        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S"); backup_dir = BACKUP_DIR / f"BACKUP_{timestamp}"; backup_dir.mkdir(parents=True, exist_ok=True)
        success = failed = 0; names = ("wireless", "network", "dhcp", "dawn")
        for router in self.routers:
            ip = router["ip"]; node_dir = backup_dir / ip; node_dir.mkdir(parents=True, exist_ok=True); ssh = None
            try:
                ssh = self.make_ssh_client(ip, timeout=6)
                for name in names:
                    out, _err, _code = self.ssh_command(ssh, f"cat /etc/config/{shlex.quote(name)} 2>/dev/null || true")
                    (node_dir / name).write_text(out, encoding="utf-8")
                (node_dir / "metadata.json").write_text(json.dumps({"ip": ip, "name": router["name"], "created": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False, indent=2), encoding="utf-8")
                success += 1; self.log(f"[ZÁLOHA OK] {ip}")
            except Exception as exc:
                failed += 1; (node_dir / "ERROR.txt").write_text(str(exc), encoding="utf-8"); self.log(f"[ZÁLOHA CHYBA] {ip}: {exc}")
            finally:
                if ssh is not None: ssh.close()
        summary = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "success_nodes": success, "failed_nodes": failed, "nodes": [r["ip"] for r in self.routers]}
        (backup_dir / "backup_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": failed == 0, "backup_dir": str(backup_dir), "success": success, "failed": failed}

    def ping_all(self) -> Dict[str, Any]:
        results = []
        for router in self.routers:
            ip = router["ip"]
            try:
                cp = subprocess.run(["ping", "-c", "1", "-W", "1", ip], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3, check=False)
                results.append({"ip": ip, "ok": cp.returncode == 0})
            except Exception as exc:
                results.append({"ip": ip, "ok": False, "error": str(exc)})
        return {"results": results, "success": sum(r["ok"] for r in results)}

    def reboot_all(self) -> Dict[str, Any]:
        success = failed = 0
        for router in self.routers:
            ssh = None
            try:
                ssh = self.make_ssh_client(router["ip"], timeout=5); ssh.exec_command("(sleep 1; reboot) >/dev/null 2>&1 &"); success += 1; self.log(f"[REBOOT OK] {router['ip']}")
            except Exception as exc:
                failed += 1; self.log(f"[REBOOT CHYBA] {router['ip']}: {exc}")
            finally:
                if ssh is not None: ssh.close()
        return {"ok": failed == 0, "success": success, "failed": failed}

    def maintenance_status(self) -> Dict[str, Any]:
        ssh = None
        try:
            ssh = self.make_ssh_client(self.main_node, timeout=6)
            script = r'''set -u
OVERLAY_DEV=$(df -P /overlay 2>/dev/null | awk 'NR==2 {print $1}')
OVERLAY_FREE=$(df -hP /overlay 2>/dev/null | awk 'NR==2 {print $4}')
[ -n "$OVERLAY_DEV" ] || OVERLAY_DEV='N/A'
[ -n "$OVERLAY_FREE" ] || OVERLAY_FREE='N/A'
case "$OVERLAY_DEV" in /dev/sd*) OVERLAY_TYPE='USB overlay' ;; *) OVERLAY_TYPE='Vnitřní paměť' ;; esac
if command -v apk >/dev/null 2>&1; then PKG='apk'; elif command -v opkg >/dev/null 2>&1; then PKG='opkg'; else PKG='nenalezen'; fi
LED_MODE=$(cat /etc/mesh_led_mode 2>/dev/null || echo default)
USB_DEV=$(ls /dev/sd[a-z] 2>/dev/null | head -n1); [ -n "$USB_DEV" ] || USB_DEV='nenalezen'
printf 'OVERLAY_DEV=%s\nOVERLAY_TYPE=%s\nOVERLAY_FREE=%s\nPKG=%s\nLED_MODE=%s\nUSB_DEV=%s\n' "$OVERLAY_DEV" "$OVERLAY_TYPE" "$OVERLAY_FREE" "$PKG" "$LED_MODE" "$USB_DEV"
'''
            out, err, code = self.ssh_script(ssh, script, timeout=20)
            if code != 0: raise RuntimeError((err or out).strip() or f"návratový kód {code}")
            values = {}
            for line in out.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1); values[k.strip()] = v.strip()
            return {"ok": True, "values": values}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "values": {}}
        finally:
            if ssh is not None: ssh.close()

    @staticmethod
    def make_persistent_led_script(mode: str) -> str:
        quoted_mode = shlex.quote(mode)
        return f'''set -e
MODE={quoted_mode}
cat > /etc/init.d/mesh-led-mode <<'EOS'
#!/bin/sh /etc/rc.common
START=99
STOP=01
apply_mode() {{
    mode=$(cat /etc/mesh_led_mode 2>/dev/null || echo default)
    case "$mode" in
        off) for led in /sys/class/leds/*; do [ -d "$led" ] || continue; [ -w "$led/trigger" ] && echo none > "$led/trigger" 2>/dev/null || true; [ -w "$led/brightness" ] && echo 0 > "$led/brightness" 2>/dev/null || true; done ;;
        on) for led in /sys/class/leds/*; do [ -d "$led" ] || continue; [ -w "$led/trigger" ] && echo none > "$led/trigger" 2>/dev/null || true; max=$(cat "$led/max_brightness" 2>/dev/null || echo 1); [ -w "$led/brightness" ] && echo "$max" > "$led/brightness" 2>/dev/null || true; done ;;
        default|*) [ -x /etc/init.d/led ] && /etc/init.d/led restart 2>/dev/null || true ;;
    esac
}}
start() {{ apply_mode; }}
boot() {{ sleep 8; apply_mode; }}
reload() {{ apply_mode; }}
EOS
chmod 0755 /etc/init.d/mesh-led-mode
printf '%s\n' "$MODE" > /etc/mesh_led_mode
touch /etc/sysupgrade.conf
grep -qxF '/etc/init.d/mesh-led-mode' /etc/sysupgrade.conf 2>/dev/null || echo '/etc/init.d/mesh-led-mode' >> /etc/sysupgrade.conf
grep -qxF '/etc/mesh_led_mode' /etc/sysupgrade.conf 2>/dev/null || echo '/etc/mesh_led_mode' >> /etc/sysupgrade.conf
/etc/init.d/mesh-led-mode enable
/etc/init.d/mesh-led-mode restart
echo "LED_MODE=$MODE"
'''

    def led_mode(self, mode: str, targets: Optional[List[str]] = None) -> Dict[str, Any]:
        if mode not in {"off", "on", "default"}: raise ValueError("Neplatný LED režim")
        targets = targets or [r["ip"] for r in self.routers]; success = failed = 0; details = []
        for ip in targets:
            ssh = None
            try:
                ssh = self.make_ssh_client(ip, timeout=6); out, err, code = self.ssh_script(ssh, self.make_persistent_led_script(mode), timeout=30)
                ok = code == 0 and f"LED_MODE={mode}" in out; success += int(ok); failed += int(not ok); details.append({"ip": ip, "ok": ok, "detail": (err or out).strip()})
            except Exception as exc:
                failed += 1; details.append({"ip": ip, "ok": False, "detail": str(exc)})
            finally:
                if ssh is not None: ssh.close()
        return {"ok": failed == 0, "success": success, "failed": failed, "details": details}

    @staticmethod
    def make_package_update_script() -> str:
        return r'''set -e
if command -v apk >/dev/null 2>&1; then echo 'PACKAGE_MANAGER=apk'; apk update; apk upgrade
elif command -v opkg >/dev/null 2>&1; then echo 'PACKAGE_MANAGER=opkg'; opkg update; UPGRADABLE=$(opkg list-upgradable | awk '{print $1}'); if [ -n "$UPGRADABLE" ]; then opkg upgrade $UPGRADABLE; else echo 'Žádné aktualizace.'; fi
else echo 'Nenalezen apk ani opkg.' >&2; exit 127; fi
echo 'UPDATE_OK'
'''

    def update_all(self) -> Dict[str, Any]:
        success = failed = 0; details = []
        for router in self.routers:
            ip = router["ip"]; ssh = None
            try:
                ssh = self.make_ssh_client(ip, timeout=8); out, err, code = self.ssh_script(ssh, self.make_package_update_script(), timeout=180); ok = code == 0 and "UPDATE_OK" in out
                success += int(ok); failed += int(not ok); details.append({"ip": ip, "ok": ok, "detail": (err or out).strip()[-3000:]})
            except Exception as exc:
                failed += 1; details.append({"ip": ip, "ok": False, "detail": str(exc)})
            finally:
                if ssh is not None: ssh.close()
        return {"ok": failed == 0, "success": success, "failed": failed, "details": details}

    @staticmethod
    def q(value: str) -> str:
        return shlex.quote(value)

    def make_safe_mesh_script(self, settings: Dict[str, str], is_main: bool) -> str:
        q = self.q; mesh_fwding = "0" if is_main else "1"; dhcp_ignore = "0" if is_main else "1"
        service_commands = "/etc/init.d/dnsmasq enable; /etc/init.d/dnsmasq restart" if is_main else "/etc/init.d/dnsmasq stop; /etc/init.d/dnsmasq disable"
        return f'''#!/bin/sh
set -eu
SSID_MAIN={q(settings['ssid_main'])}
SSID_LEGACY={q(settings['ssid_legacy'])}
KEY={q(settings['key'])}
MESH_ID={q(settings['mesh_id'])}
COUNTRY={q(settings['country'])}
MOBILITY={q(settings['mobility'])}
CH24={q(settings['channel_24'])}
CH5={q(settings['channel_5'])}
TXPOWER={q(settings['txpower'])}
uci export wireless > /tmp/wireless.before_safe_mesh 2>/dev/null || true
uci export dhcp > /tmp/dhcp.before_safe_mesh 2>/dev/null || true
SECTIONS=$(uci show wireless | awk -F'[.=]' '/=wifi-iface$/ {{print $2}}' | awk '{{a[NR]=$0}} END {{for(i=NR;i>0;i--) print a[i]}}')
for i in $SECTIONS; do MODE=$(uci -q get wireless.$i.mode || true); if [ "$MODE" = "ap" ] || [ "$MODE" = "mesh" ]; then uci -q delete wireless.$i || true; fi; done
uci set wireless.radio0.country="$COUNTRY"; uci set wireless.radio1.country="$COUNTRY"
uci set wireless.radio0.channel="$CH24"; uci set wireless.radio0.htmode='HE20'; uci set wireless.radio0.txpower="$TXPOWER"
uci set wireless.radio1.channel="$CH5"; uci set wireless.radio1.htmode='HE80'; uci set wireless.radio1.txpower="$TXPOWER"
uci set wireless.ap_main_24='wifi-iface'; uci set wireless.ap_main_24.device='radio0'; uci set wireless.ap_main_24.mode='ap'; uci set wireless.ap_main_24.ssid="$SSID_MAIN"; uci set wireless.ap_main_24.encryption='sae-mixed'; uci set wireless.ap_main_24.key="$KEY"; uci set wireless.ap_main_24.network='lan'; uci set wireless.ap_main_24.ieee80211r='1'; uci set wireless.ap_main_24.ieee80211k='1'; uci set wireless.ap_main_24.ieee80211v='1'; uci set wireless.ap_main_24.mobility_domain="$MOBILITY"; uci set wireless.ap_main_24.ft_over_ds='0'
uci set wireless.ap_main_5='wifi-iface'; uci set wireless.ap_main_5.device='radio1'; uci set wireless.ap_main_5.mode='ap'; uci set wireless.ap_main_5.ssid="$SSID_MAIN"; uci set wireless.ap_main_5.encryption='sae-mixed'; uci set wireless.ap_main_5.key="$KEY"; uci set wireless.ap_main_5.network='lan'; uci set wireless.ap_main_5.ieee80211r='1'; uci set wireless.ap_main_5.ieee80211k='1'; uci set wireless.ap_main_5.ieee80211v='1'; uci set wireless.ap_main_5.mobility_domain="$MOBILITY"; uci set wireless.ap_main_5.ft_over_ds='0'
uci set wireless.ap_legacy_24='wifi-iface'; uci set wireless.ap_legacy_24.device='radio0'; uci set wireless.ap_legacy_24.mode='ap'; uci set wireless.ap_legacy_24.ssid="$SSID_LEGACY"; uci set wireless.ap_legacy_24.encryption='psk2'; uci set wireless.ap_legacy_24.key="$KEY"; uci set wireless.ap_legacy_24.network='lan'
uci set wireless.mesh_backhaul='wifi-iface'; uci set wireless.mesh_backhaul.device='radio1'; uci set wireless.mesh_backhaul.mode='mesh'; uci set wireless.mesh_backhaul.mesh_id="$MESH_ID"; uci set wireless.mesh_backhaul.encryption='sae'; uci set wireless.mesh_backhaul.key="$KEY"; uci set wireless.mesh_backhaul.network='lan'; uci set wireless.mesh_backhaul.mesh_fwding='{mesh_fwding}'
uci set dhcp.lan.ignore='{dhcp_ignore}'; uci commit wireless; uci commit dhcp
echo 'CONFIG_STAGED_OK'
(sleep 2; wifi reload; /etc/init.d/network restart; {service_commands}; /etc/init.d/dawn restart 2>/dev/null || true) >/tmp/safe_mesh_apply.log 2>&1 &
exit 0
'''

    def safe_mesh_deploy(self, settings: Dict[str, str]) -> Dict[str, Any]:
        required = ["ssid_main", "ssid_legacy", "key", "mesh_id", "country", "mobility", "channel_24", "channel_5", "txpower"]
        if any(not str(settings.get(k, "")).strip() for k in required): raise ValueError("Chybí hodnoty SAFE MESH")
        if len(settings["key"]) < 8: raise ValueError("Wi-Fi heslo musí mít alespoň 8 znaků")
        if not re.fullmatch(r"[0-9A-Fa-f]{4}", settings["mobility"]): raise ValueError("Mobility domain musí mít 4 hex znaky")
        if not re.fullmatch(r"[A-Za-z]{2}", settings["country"]): raise ValueError("Kód země musí mít 2 znaky")
        settings = {k: str(settings[k]).strip() for k in required}; settings["country"] = settings["country"].upper()
        backup = self.backup_configs()
        if backup["failed"]:
            return {"ok": False, "stopped": True, "reason": "Záloha před nasazením nebyla úplná", "backup": backup}
        success = failed = 0; details = []
        ordered = sorted(self.routers, key=lambda r: 0 if r["ip"] == self.main_node else 1)
        for router in ordered:
            ip = router["ip"]; ssh = None
            try:
                ssh = self.make_ssh_client(ip, timeout=8); out, err, code = self.ssh_script(ssh, self.make_safe_mesh_script(settings, ip == self.main_node), timeout=40); ok = code == 0 and "CONFIG_STAGED_OK" in out
                success += int(ok); failed += int(not ok); details.append({"ip": ip, "ok": ok, "detail": (err or out).strip()})
            except Exception as exc:
                failed += 1; details.append({"ip": ip, "ok": False, "detail": str(exc)})
            finally:
                if ssh is not None: ssh.close()
            time.sleep(0.4)
        return {"ok": failed == 0, "success": success, "failed": failed, "details": details, "backup": backup}

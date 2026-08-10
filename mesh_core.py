from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import threading
import time
import zipfile
import tarfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import paramiko

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
BACKUP_DIR = DATA_DIR / "backups"
CONFIG_FILE = DATA_DIR / "config.json"
EXAMPLE_CONFIG = Path(__file__).with_name("config.example.json")

DEFAULT_CONFIG = {
    "routers": [
        {"ip": "192.168.30.1", "name": "ROUTER", "backup_name": "ROUTER.tar.gz"},
        {"ip": "192.168.30.2", "name": "MESH1", "backup_name": "MESH1.tar.gz"},
        {"ip": "192.168.30.3", "name": "MESH2", "backup_name": "MESH2.tar.gz"},
        {"ip": "192.168.30.4", "name": "MESH3", "backup_name": "MESH3.tar.gz"},
        {"ip": "192.168.30.5", "name": "MESH4", "backup_name": "MESH4.tar.gz"},
    ],
    "ssh": {"user": "root", "password": "root", "key_file": "", "timeout": 5},
    "refresh_seconds": 30,
}

MAC_RE = re.compile(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", re.I)


def normalize_radio_band(value: Any) -> str:
    """Převede OpenWrt band/hwmode/radio označení na text pro UI."""
    raw = str(value or "").strip().lower().replace(" ", "")
    if not raw:
        return ""
    if any(token in raw for token in ("2g", "2.4", "2,4", "11g", "11b")) or raw == "radio0":
        return "2.4 GHz"
    if any(token in raw for token in ("5g", "5ghz", "11a")) or raw == "radio1":
        return "5 GHz"
    if any(token in raw for token in ("6g", "6ghz")) or raw == "radio2":
        return "6 GHz"
    return ""


def ensure_config() -> Dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))

    # Migrace starších webových verzí: zachovej uživatelská nastavení, ale
    # doplň pevné názvy OpenWrt záloh podle IP adresy.
    backup_names = {
        "192.168.30.1": "ROUTER.tar.gz",
        "192.168.30.2": "MESH1.tar.gz",
        "192.168.30.3": "MESH2.tar.gz",
        "192.168.30.4": "MESH3.tar.gz",
        "192.168.30.5": "MESH4.tar.gz",
    }
    changed = False
    routers = cfg.get("routers")
    if not isinstance(routers, list) or not routers:
        cfg["routers"] = json.loads(json.dumps(DEFAULT_CONFIG["routers"]))
        routers = cfg["routers"]
        changed = True
    for router in routers:
        ip = str(router.get("ip", ""))
        wanted = backup_names.get(ip)
        if wanted and router.get("backup_name") != wanted:
            router["backup_name"] = wanted
            changed = True
    if "ssh" not in cfg:
        cfg["ssh"] = json.loads(json.dumps(DEFAULT_CONFIG["ssh"]))
        changed = True
    if changed:
        CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


@dataclass
class NodeState:
    ip: str
    name: str
    online: bool = False
    hostname: str = ""
    uptime: str = ""
    clients: int = 0
    error: str = ""


class OperationState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with getattr(self, "_lock", threading.Lock()):
            self.data = {
                "running": False,
                "title": "Připraveno",
                "percent": 0,
                "current": "",
                "started": None,
                "finished": None,
                "nodes": {},
                "log": [],
                "result": "",
            }

    def start(self, title: str, routers: List[Dict[str, str]]) -> bool:
        with self._lock:
            if self.data["running"]:
                return False
            self.data = {
                "running": True,
                "title": title,
                "percent": 0,
                "current": "Připravuji…",
                "started": time.time(),
                "finished": None,
                "nodes": {r["ip"]: {"name": r["name"], "state": "ČEKÁ", "detail": ""} for r in routers},
                "log": [],
                "result": "",
            }
            return True

    def update(self, *, percent: Optional[int] = None, current: Optional[str] = None,
               ip: Optional[str] = None, state: Optional[str] = None, detail: str = "",
               log: Optional[str] = None) -> None:
        with self._lock:
            if percent is not None:
                self.data["percent"] = max(0, min(100, int(percent)))
            if current is not None:
                self.data["current"] = current
            if ip and ip in self.data["nodes"] and state:
                self.data["nodes"][ip]["state"] = state
                self.data["nodes"][ip]["detail"] = detail
            if log:
                stamp = time.strftime("%H:%M:%S")
                self.data["log"].append(f"[{stamp}] {log}")
                self.data["log"] = self.data["log"][-120:]

    def finish(self, result: str) -> None:
        with self._lock:
            self.data["running"] = False
            self.data["percent"] = 100
            self.data["current"] = result
            self.data["result"] = result
            self.data["finished"] = time.time()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            out = json.loads(json.dumps(self.data))
        if out.get("started"):
            end = time.time() if out["running"] else (out.get("finished") or time.time())
            out["elapsed"] = max(0, int(end - out["started"]))
        else:
            out["elapsed"] = 0
        return out


class MeshController:
    def __init__(self) -> None:
        self.cfg = ensure_config()
        self.routers: List[Dict[str, str]] = self.cfg.get("routers", DEFAULT_CONFIG["routers"])
        self.operation = OperationState()
        self._status_lock = threading.Lock()
        self._snapshot: Dict[str, Any] = {"nodes": [], "links": [], "clients": [], "updated": None}

    def reload_config(self) -> None:
        self.cfg = ensure_config()
        self.routers = self.cfg.get("routers", DEFAULT_CONFIG["routers"])

    def ssh_client(self, ip: str, timeout: Optional[int] = None) -> paramiko.SSHClient:
        ssh_cfg = self.cfg.get("ssh", {})
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: Dict[str, Any] = {
            "hostname": ip,
            "username": ssh_cfg.get("user", "root"),
            "timeout": timeout or int(ssh_cfg.get("timeout", 5)),
            "banner_timeout": timeout or int(ssh_cfg.get("timeout", 5)),
            "auth_timeout": timeout or int(ssh_cfg.get("timeout", 5)),
            "look_for_keys": False,
            "allow_agent": False,
        }
        key_file = str(ssh_cfg.get("key_file", "") or "").strip()
        password = str(ssh_cfg.get("password", "") or "")
        if key_file:
            kwargs["key_filename"] = key_file
        else:
            kwargs["password"] = password
        client.connect(**kwargs)
        return client

    @staticmethod
    def command(client: paramiko.SSHClient, command: str, timeout: int = 30) -> Tuple[str, str, int]:
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return out, err, code

    @staticmethod
    def command_bytes(client: paramiko.SSHClient, command: str, timeout: int = 60) -> Tuple[bytes, str, int]:
        # Binární stdout pro OpenWrt zálohy; nevyžaduje SFTP subsystem.
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        blob = stdout.read()
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        return blob, err, code

    @staticmethod
    def script(client: paramiko.SSHClient, script: str, timeout: int = 60) -> Tuple[str, str, int]:
        stdin, stdout, stderr = client.exec_command("sh -s", timeout=timeout)
        stdin.write(script)
        stdin.channel.shutdown_write()
        code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return out, err, code

    def get_snapshot(self) -> Dict[str, Any]:
        with self._status_lock:
            return json.loads(json.dumps(self._snapshot))

    def runtime_routers(self) -> List[Dict[str, str]]:
        """Vrátí konfiguraci routerů s aktuálním hostname jako zobrazovaným názvem."""
        snap = self.get_snapshot()
        names = {
            str(n.get("ip", "")): str(n.get("hostname") or n.get("name") or "").strip()
            for n in snap.get("nodes", [])
            if isinstance(n, dict)
        }
        result: List[Dict[str, str]] = []
        for router in self.routers:
            item = dict(router)
            item["name"] = names.get(router["ip"]) or router.get("name") or router["ip"]
            result.append(item)
        return result

    def refresh_snapshot(self) -> Dict[str, Any]:
        # Robustní klientská detekce: Wi-Fi station + FDB + ARP + DHCP fallback.
        node_states: List[Dict[str, Any]] = []
        raw_nodes: Dict[str, Dict[str, Any]] = {}
        mac_to_ip: Dict[str, str] = {}

        for router in self.routers:
            ip = router["ip"]
            state = NodeState(ip=ip, name=router["name"])
            data: Dict[str, Any] = {
                "mesh_peers": [], "local_macs": [], "mesh_macs": [],
                "wifi_clients": [], "neighbors": [], "leases": {}, "fdb": [], "ports": [],
            }
            client = None
            try:
                client = self.ssh_client(ip, 5)
                cmd = r'''host_value="$(uci -q get system.@system[0].hostname 2>/dev/null || true)"
[ -n "$host_value" ] || host_value="$(cat /proc/sys/kernel/hostname 2>/dev/null || true)"
printf 'HOST=%s\n' "$host_value"
printf 'UP='; cut -d. -f1 /proc/uptime 2>/dev/null || true
printf 'MACS='; for f in /sys/class/net/*/address; do cat "$f" 2>/dev/null; done | tr '\n' ' '; echo
printf 'WIRELESS_BEGIN\n'; ubus call network.wireless status 2>/dev/null || true; printf '\nWIRELESS_END\n'
printf 'IW_BEGIN\n'; iw dev 2>/dev/null || true; printf '\nIW_END\n'
printf 'NEIGH_BEGIN\n'; ip -4 neigh show dev br-lan 2>/dev/null || ip neigh show dev br-lan 2>/dev/null || true; printf '\nNEIGH_END\n'
printf 'LEASES_BEGIN\n'; cat /tmp/dhcp.leases 2>/dev/null || true; printf '\nLEASES_END\n'
printf 'FDB_BEGIN\n'; if command -v bridge >/dev/null 2>&1; then echo __BRIDGE__; bridge fdb show 2>/dev/null || true; elif command -v brctl >/dev/null 2>&1; then echo __BRCTL__; brctl showmacs br-lan 2>/dev/null || true; else echo __NONE__; fi; printf '\nFDB_END\n'
printf 'PORTS_BEGIN\n'; \
for b in /sys/class/net/br-lan/brif/*; do \
  [ -e "$b" ] || continue; \
  p=$(basename "$b"); \
  case "$p" in wlan*|phy*|mesh*|wds*|bat*|ifb*|veth*|tap*|tun*) continue ;; esac; \
  oper=$(cat /sys/class/net/"$p"/operstate 2>/dev/null || echo unknown); \
  carrier=$(cat /sys/class/net/"$p"/carrier 2>/dev/null || echo 0); \
  speed=$(cat /sys/class/net/"$p"/speed 2>/dev/null || true); \
  printf '%s\t%s\t%s\t%s\n' "$p" "$oper" "$carrier" "$speed"; \
done; printf 'PORTS_END\n'
'''
                out, _err, _code = self.command(client, cmd, 20)
                state.online = True

                host = re.search(r"^HOST=(.*)$", out, re.M)
                up = re.search(r"^UP=(.*)$", out, re.M)
                macs = re.search(r"^MACS=(.*)$", out, re.M)
                state.hostname = host.group(1).strip() if host else ""
                # Ochrana proti slepenému výstupu starších BusyBoxů: hodnota UP=... nikdy není hostname.
                if state.hostname.upper().startswith("UP=") or state.hostname in {"", "localhost", "(none)"}:
                    state.hostname = ""
                # Zobrazený název se vždy řídí skutečným hostname routeru.
                # Konfigurační name zůstává pouze jako fallback pro offline uzel.
                if state.hostname:
                    state.name = state.hostname
                if up and up.group(1).strip().isdigit():
                    sec = int(up.group(1).strip())
                    state.uptime = f"{sec // 86400}d {(sec % 86400) // 3600}h"
                if macs:
                    data["local_macs"] = sorted(set(m.lower() for m in MAC_RE.findall(macs.group(1))))
                    for mac in data["local_macs"]:
                        mac_to_ip[mac] = ip

                w = re.search(r"WIRELESS_BEGIN\n(.*?)\nWIRELESS_END", out, re.S)
                try:
                    wireless_json = json.loads(w.group(1).strip() or "{}") if w else {}
                except Exception:
                    wireless_json = {}

                iface_info: Dict[str, Dict[str, str]] = {}
                if isinstance(wireless_json, dict):
                    for radio, radio_data in wireless_json.items():
                        if not isinstance(radio_data, dict):
                            continue
                        radio_cfg = radio_data.get("config", {}) or {}
                        band_raw = str(radio_cfg.get("band") or radio_cfg.get("hwmode") or radio)
                        for iface in radio_data.get("interfaces", []) or []:
                            if not isinstance(iface, dict):
                                continue
                            cfg = iface.get("config", {}) or {}
                            ifname = str(iface.get("ifname") or "").strip()
                            if not ifname:
                                continue
                            iface_info[ifname] = {
                                "mode": str(cfg.get("mode") or "").lower(),
                                "ssid": str(cfg.get("ssid") or cfg.get("mesh_id") or ""),
                                "band": band_raw,
                            }

                iw_match = re.search(r"IW_BEGIN\n(.*?)\nIW_END", out, re.S)
                iw_text = iw_match.group(1) if iw_match else ""
                for block in re.split(r"\n\s*Interface\s+", "\n" + iw_text)[1:]:
                    lines = block.strip().splitlines()
                    if not lines:
                        continue
                    ifname = lines[0].strip()
                    body = "\n".join(lines[1:])
                    info = iface_info.setdefault(ifname, {"mode": "", "ssid": "", "band": ""})
                    if re.search(r"\btype\s+mesh point\b", body):
                        info["mode"] = "mesh"
                    elif re.search(r"\btype\s+AP\b", body, re.I) and not info.get("mode"):
                        info["mode"] = "ap"

                for ifname, info in iface_info.items():
                    mode = info.get("mode", "")
                    if mode not in {"ap", "mesh", "mesh_point", "mp"}:
                        continue
                    safe_if = shlex.quote(ifname)
                    iface_mac_out, _, _ = self.command(client, f"cat /sys/class/net/{safe_if}/address 2>/dev/null || true", 5)
                    iface_macs = [m.lower() for m in MAC_RE.findall(iface_mac_out)]
                    if mode in {"mesh", "mesh_point", "mp"}:
                        data["mesh_macs"].extend(iface_macs)

                    station_out, _, _ = self.command(client, f"iw dev {safe_if} station dump 2>/dev/null || true", 10)
                    current: Optional[Dict[str, Any]] = None
                    stations: List[Dict[str, Any]] = []
                    for line in station_out.splitlines():
                        text = line.strip()
                        m = re.match(r"^Station\s+([0-9a-f:]{17})", text, re.I)
                        if m:
                            if current:
                                stations.append(current)
                            current = {"mac": m.group(1).lower(), "signal": None, "tx": "", "rx": ""}
                            continue
                        if not current:
                            continue
                        sig = re.match(r"^signal(?: avg)?:\s*(-?\d+)", text, re.I)
                        if sig and current["signal"] is None:
                            current["signal"] = int(sig.group(1))
                        tx = re.match(r"^tx bitrate:\s*([^\n]+)", text, re.I)
                        if tx:
                            current["tx"] = tx.group(1).strip()
                        rx = re.match(r"^rx bitrate:\s*([^\n]+)", text, re.I)
                        if rx:
                            current["rx"] = rx.group(1).strip()
                    if current:
                        stations.append(current)

                    if mode == "ap":
                        for sta in stations:
                            data["wifi_clients"].append({
                                "mac": sta["mac"], "ifname": ifname,
                                "ssid": info.get("ssid", ""), "signal": sta.get("signal"),
                                "tx": sta.get("tx", ""), "rx": sta.get("rx", ""),
                                "band": normalize_radio_band(info.get("band", "")),
                            })
                    else:
                        for sta in stations:
                            data["mesh_peers"].append({
                                "mac": sta["mac"], "signal": sta.get("signal"),
                                "speed": sta.get("tx", ""), "ifname": ifname,
                            })

                neigh_match = re.search(r"NEIGH_BEGIN\n(.*?)\nNEIGH_END", out, re.S)
                for line in (neigh_match.group(1) if neigh_match else "").splitlines():
                    m = re.search(r"^(\S+)\s+dev\s+(\S+).*?\blladdr\s+([0-9a-f:]{17})\b(?:.*?\s([A-Z]+))?$", line.strip(), re.I)
                    if not m:
                        continue
                    nip, dev, mac, nstate = m.groups()
                    nstate = (nstate or "UNKNOWN").upper()
                    if nstate in {"FAILED", "INCOMPLETE", "NOARP", "NONE"}:
                        continue
                    data["neighbors"].append({"ip": nip, "dev": dev, "mac": mac.lower(), "state": nstate})

                lease_match = re.search(r"LEASES_BEGIN\n(.*?)\nLEASES_END", out, re.S)
                for line in (lease_match.group(1) if lease_match else "").splitlines():
                    parts = line.split()
                    if len(parts) < 4 or not MAC_RE.fullmatch(parts[1]):
                        continue
                    data["leases"][parts[1].lower()] = {
                        "ip": parts[2], "hostname": "" if parts[3] == "*" else parts[3]
                    }

                fdb_match = re.search(r"FDB_BEGIN\n(.*?)\nFDB_END", out, re.S)
                fdb_lines = (fdb_match.group(1) if fdb_match else "").splitlines()
                method = fdb_lines[0].strip() if fdb_lines else "__NONE__"
                for line in fdb_lines[1:]:
                    text = line.strip()
                    if not text:
                        continue
                    if method == "__BRIDGE__":
                        m = re.match(r"^([0-9a-f:]{17})\s+dev\s+(\S+)", text, re.I)
                        if not m:
                            continue
                        mac, port = m.group(1).lower(), m.group(2)
                        flags = set(text.lower().split())
                        if flags.intersection({"self", "permanent", "local"}):
                            continue
                        if port.lower().startswith(("wlan", "mesh", "phy")):
                            continue
                        data["fdb"].append({"mac": mac, "port": port})
                    elif method == "__BRCTL__":
                        m = re.match(r"^(\d+)\s+([0-9a-f:]{17})\s+(yes|no)\s+", text, re.I)
                        if m and m.group(3).lower() == "no":
                            data["fdb"].append({"mac": m.group(2).lower(), "port": "br-lan"})

                ports_match = re.search(r"PORTS_BEGIN\n(.*?)\nPORTS_END", out, re.S)
                for line in (ports_match.group(1) if ports_match else "").splitlines():
                    parts = line.strip().split("\t")
                    if len(parts) < 4:
                        parts = line.strip().split()
                    if len(parts) < 3:
                        continue
                    port = parts[0].strip()
                    oper = parts[1].strip().lower()
                    carrier = parts[2].strip() == "1"
                    speed_raw = parts[3].strip() if len(parts) > 3 else ""
                    try:
                        speed = int(speed_raw) if int(speed_raw) > 0 else None
                    except (ValueError, TypeError):
                        speed = None
                    data["ports"].append({
                        "name": port,
                        "up": bool(carrier or oper == "up"),
                        "operstate": oper,
                        "speed_mbps": speed,
                    })

            except Exception as exc:
                state.error = str(exc)
                state.online = False
            finally:
                if client:
                    client.close()
            raw_nodes[ip] = data
            node_states.append(asdict(state))

        mesh_mac_to_ip: Dict[str, str] = dict(mac_to_ip)
        for node_ip, data in raw_nodes.items():
            for mac in data.get("mesh_macs", []):
                mesh_mac_to_ip[mac] = node_ip

        links_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for source_ip, data in raw_nodes.items():
            for peer in data.get("mesh_peers", []):
                target_ip = mesh_mac_to_ip.get(peer.get("mac", ""))
                if not target_ip or target_ip == source_ip:
                    continue
                key = tuple(sorted((source_ip, target_ip)))
                link = links_by_key.setdefault(key, {"a": key[0], "b": key[1], "signals": [], "speeds": []})
                if peer.get("signal") is not None:
                    link["signals"].append(peer["signal"])
                speed_text = str(peer.get("speed") or "")
                sm = re.search(r"([0-9.]+)\s*MBit/s", speed_text, re.I)
                if sm:
                    link["speeds"].append(float(sm.group(1)))

        links: List[Dict[str, Any]] = []
        for link in links_by_key.values():
            signal = round(sum(link["signals"]) / len(link["signals"])) if link["signals"] else None
            speed = max(link["speeds"]) if link["speeds"] else None
            links.append({"a": link["a"], "b": link["b"], "dbm": signal, "speed_mbps": speed})

        local_macs = {m for data in raw_nodes.values() for m in data.get("local_macs", [])}
        mesh_macs = {m for data in raw_nodes.values() for m in data.get("mesh_macs", [])}
        lease_map: Dict[str, Dict[str, str]] = {}
        neigh_ip: Dict[str, str] = {}
        for data in raw_nodes.values():
            lease_map.update(data.get("leases", {}))
            for n in data.get("neighbors", []):
                neigh_ip.setdefault(n["mac"], n["ip"])

        display_names = {
            state["ip"]: (state.get("hostname") or state.get("name") or state["ip"])
            for state in node_states
        }

        clients_by_mac: Dict[str, Dict[str, Any]] = {}
        for router in self.routers:
            data = raw_nodes.get(router["ip"], {})
            for wclient in data.get("wifi_clients", []):
                mac = wclient["mac"]
                if mac in local_macs or mac in mesh_macs:
                    continue
                lease = lease_map.get(mac, {})
                details = []
                if wclient.get("ssid"):
                    details.append(wclient["ssid"])
                if wclient.get("signal") is not None:
                    details.append(f"{wclient['signal']} dBm")
                clients_by_mac[mac] = {
                    "node": display_names.get(router["ip"], router["name"]), "node_ip": router["ip"],
                    "ip": lease.get("ip") or neigh_ip.get(mac, ""),
                    "mac": mac, "hostname": lease.get("hostname", ""),
                    "type": "Wi-Fi", "radio": wclient.get("band", ""),
                    "detail": " · ".join(details),
                }

        for router in self.routers:
            data = raw_nodes.get(router["ip"], {})
            for fdb in data.get("fdb", []):
                mac = fdb["mac"]
                if mac in clients_by_mac or mac in local_macs or mac in mesh_macs:
                    continue
                lease = lease_map.get(mac, {})
                clients_by_mac[mac] = {
                    "node": display_names.get(router["ip"], router["name"]), "node_ip": router["ip"],
                    "ip": lease.get("ip") or neigh_ip.get(mac, ""),
                    "mac": mac, "hostname": lease.get("hostname", ""),
                    "type": "LAN", "radio": "", "detail": fdb.get("port", "br-lan"),
                }

        for router in self.routers:
            data = raw_nodes.get(router["ip"], {})
            for n in data.get("neighbors", []):
                mac = n["mac"]
                if mac in clients_by_mac or mac in local_macs or mac in mesh_macs:
                    continue
                lease = lease_map.get(mac, {})
                clients_by_mac[mac] = {
                    "node": display_names.get(router["ip"], router["name"]), "node_ip": router["ip"],
                    "ip": lease.get("ip") or n.get("ip", ""), "mac": mac,
                    "hostname": lease.get("hostname", ""), "type": "Neurčené",
                    "radio": "", "detail": f"ARP {n.get('state', '')}".strip(),
                }

        main_name = display_names.get(self.routers[0]["ip"], self.routers[0]["name"]) if self.routers else "ROUTER"
        main_ip = self.routers[0]["ip"] if self.routers else "192.168.30.1"
        for mac, lease in lease_map.items():
            if mac in clients_by_mac or mac in local_macs or mac in mesh_macs:
                continue
            clients_by_mac[mac] = {
                "node": main_name, "node_ip": main_ip, "ip": lease.get("ip", ""),
                "mac": mac, "hostname": lease.get("hostname", ""),
                "type": "DHCP", "radio": "", "detail": "lease",
            }

        clients = sorted(clients_by_mac.values(), key=lambda c: (c.get("node_ip", ""), c.get("ip", ""), c["mac"]))
        counts: Dict[str, int] = {}
        for item in clients:
            counts[item.get("node_ip", "")] = counts.get(item.get("node_ip", ""), 0) + 1
        for state in node_states:
            state["clients"] = counts.get(state["ip"], 0)
            ports = raw_nodes.get(state["ip"], {}).get("ports", [])
            def _port_sort_key(item: Dict[str, Any]) -> Tuple[Any, ...]:
                name = str(item.get("name", ""))
                m = re.match(r"^(.*?)(\d+)$", name)
                return (m.group(1).lower(), int(m.group(2))) if m else (name.lower(), 0)
            state["ports"] = sorted(ports, key=_port_sort_key)

        snapshot = {"nodes": node_states, "links": links, "clients": clients, "updated": time.time()}
        with self._status_lock:
            self._snapshot = snapshot
        return snapshot

    def _run_per_router(self, title: str, worker: Callable[[Dict[str, str]], Tuple[bool, str]], result_label: str) -> None:
        routers = self.runtime_routers()
        if not self.operation.start(title, routers):
            return
        ok_count = 0
        total = len(routers)
        for index, router in enumerate(routers):
            ip = router["ip"]
            self.operation.update(percent=int(index * 100 / total), current=f"{router['name']} ({ip})…", ip=ip, state="PROBÍHÁ", log=f"{router['name']} ({ip}) – start")
            try:
                ok, detail = worker(router)
            except Exception as exc:
                ok, detail = False, str(exc)
            if ok:
                ok_count += 1
                self.operation.update(ip=ip, state="HOTOVO", detail=detail, log=f"{router['name']} – OK: {detail}")
            else:
                self.operation.update(ip=ip, state="CHYBA", detail=detail, log=f"{router['name']} – CHYBA: {detail}")
            self.operation.update(percent=int((index + 1) * 100 / total))
        self.operation.finish(f"{result_label}: {ok_count}/{total} OK")

    def start_ping(self) -> bool:
        if self.operation.snapshot()["running"]:
            return False
        def worker(router: Dict[str, str]) -> Tuple[bool, str]:
            c = self.ssh_client(router["ip"], 4)
            try:
                return True, "SSH dostupné"
            finally:
                c.close()
        threading.Thread(target=self._run_per_router, args=("Test dostupnosti uzlů", worker, "Dostupnost"), daemon=True).start()
        return True

    @staticmethod
    def update_script() -> str:
        return r'''set -e
if command -v apk >/dev/null 2>&1; then
  echo MANAGER=apk
  apk update
  apk upgrade
elif command -v opkg >/dev/null 2>&1; then
  echo MANAGER=opkg
  opkg update
  PKGS="$(opkg list-upgradable | awk '{print $1}')"
  [ -z "$PKGS" ] || opkg upgrade $PKGS
else
  echo "Nenalezen apk ani opkg" >&2
  exit 127
fi
echo UPDATE_OK
'''

    def start_update(self) -> bool:
        if self.operation.snapshot()["running"]:
            return False
        def worker(router: Dict[str, str]) -> Tuple[bool, str]:
            c = self.ssh_client(router["ip"], 8)
            try:
                out, err, code = self.script(c, self.update_script(), 1800)
                if code == 0 and "UPDATE_OK" in out:
                    manager = "apk" if "MANAGER=apk" in out else "opkg" if "MANAGER=opkg" in out else "balíčky"
                    return True, f"{manager} aktualizováno"
                return False, (err or out or f"exit {code}")[-350:]
            finally:
                c.close()
        threading.Thread(target=self._run_per_router, args=("Aktualizace HW", worker, "Aktualizace HW"), daemon=True).start()
        return True

    @staticmethod
    def led_script(mode: str) -> str:
        if mode not in {"on", "off"}:
            raise ValueError("Neplatný LED režim")
        value = "0" if mode == "off" else "MAX"
        return f'''set -e
MODE={shlex.quote(mode)}
for led in /sys/class/leds/*; do
  [ -d "$led" ] || continue
  [ -w "$led/trigger" ] && echo none > "$led/trigger" 2>/dev/null || true
  if [ "$MODE" = off ]; then
    [ -w "$led/brightness" ] && echo 0 > "$led/brightness" 2>/dev/null || true
  else
    max=$(cat "$led/max_brightness" 2>/dev/null || echo 1)
    [ -w "$led/brightness" ] && echo "$max" > "$led/brightness" 2>/dev/null || true
  fi
done
mkdir -p /etc
cat > /etc/init.d/mesh-led-mode <<'EOS'
#!/bin/sh /etc/rc.common
START=99
apply_mode() {{
  MODE=$(cat /etc/mesh_led_mode 2>/dev/null || echo off)
  for led in /sys/class/leds/*; do
    [ -d "$led" ] || continue
    [ -w "$led/trigger" ] && echo none > "$led/trigger" 2>/dev/null || true
    if [ "$MODE" = off ]; then
      [ -w "$led/brightness" ] && echo 0 > "$led/brightness" 2>/dev/null || true
    else
      max=$(cat "$led/max_brightness" 2>/dev/null || echo 1)
      [ -w "$led/brightness" ] && echo "$max" > "$led/brightness" 2>/dev/null || true
    fi
  done
}}
start() {{ apply_mode; }}
boot() {{ sleep 8; apply_mode; }}
reload() {{ apply_mode; }}
EOS
chmod 0755 /etc/init.d/mesh-led-mode
printf '%s\n' "$MODE" > /etc/mesh_led_mode
/etc/init.d/mesh-led-mode enable 2>/dev/null || true
/etc/init.d/mesh-led-mode restart 2>/dev/null || true
echo LED_OK
'''

    def start_led(self, mode: str, target: str = "all") -> bool:
        if mode not in {"on", "off"} or self.operation.snapshot()["running"]:
            return False
        runtime = self.runtime_routers()
        routers = runtime if target == "all" else [r for r in runtime if r["ip"] == target]
        if not routers:
            return False
        def run() -> None:
            if not self.operation.start(f"LED {'ON' if mode == 'on' else 'OFF'}", routers):
                return
            total = len(routers); okc = 0
            for i, r in enumerate(routers):
                ip = r["ip"]
                self.operation.update(percent=int(i*100/total), current=f"{r['name']} ({ip})…", ip=ip, state="PROBÍHÁ")
                c = None
                try:
                    c = self.ssh_client(ip, 5)
                    out, err, code = self.script(c, self.led_script(mode), 30)
                    ok = code == 0 and "LED_OK" in out
                    detail = "nastaveno" if ok else (err or out or str(code))[-250:]
                except Exception as exc:
                    ok, detail = False, str(exc)
                finally:
                    if c: c.close()
                if ok: okc += 1
                self.operation.update(ip=ip, state="HOTOVO" if ok else "CHYBA", detail=detail, log=f"{r['name']}: {detail}", percent=int((i+1)*100/total))
            self.operation.finish(f"LED {'ON' if mode == 'on' else 'OFF'}: {okc}/{total} OK")
        threading.Thread(target=run, daemon=True).start()
        return True

    def start_reboot(self) -> bool:
        """Pošle restart všem routerům a průběh zobrazí v Operation panelu."""
        if self.operation.snapshot()["running"]:
            return False

        def worker(router: Dict[str, str]) -> Tuple[bool, str]:
            c = self.ssh_client(router["ip"], 5)
            try:
                # Reboot se spustí s malým zpožděním, aby SSH stihlo vrátit potvrzení.
                out, err, code = self.command(
                    c,
                    "printf 'REBOOT_SENT\n'; (sleep 1; reboot) >/dev/null 2>&1 &",
                    8,
                )
                if code == 0 and "REBOOT_SENT" in out:
                    return True, "restart odeslán"
                return False, (err or out or f"exit {code}")[-250:]
            finally:
                c.close()

        threading.Thread(
            target=self._run_per_router,
            args=("REBOOT všech routerů", worker, "REBOOT"),
            daemon=True,
        ).start()
        return True

    def start_backup(self) -> bool:
        if self.operation.snapshot()["running"]:
            return False
        threading.Thread(target=self._backup_worker, daemon=True).start()
        return True

    def _backup_worker(self) -> None:
        routers = self.runtime_routers()
        if not self.operation.start("Záloha konfigurace OpenWrt", routers):
            return
        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        set_dir = BACKUP_DIR / timestamp
        set_dir.mkdir(parents=True, exist_ok=True)
        total = len(routers)
        success = 0
        manifest = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "files": []}
        for i, router in enumerate(routers):
            ip, name = router["ip"], router["name"]
            filename = router.get("backup_name") or f"{name}.tar.gz"
            remote = f"/tmp/{filename}"
            local = set_dir / filename
            self.operation.update(percent=int(i * 100 / total), current=f"Zálohuji {name} ({ip})…", ip=ip, state="PROBÍHÁ", log=f"{name}: vytvářím standardní sysupgrade archiv")
            client = None
            try:
                client = self.ssh_client(ip, 8)
                out, err, code = self.command(client, f"umask 077; rm -f {shlex.quote(remote)}; sysupgrade -b {shlex.quote(remote)}; test -s {shlex.quote(remote)}", 180)
                if code != 0:
                    raise RuntimeError((err or out or f"sysupgrade exit {code}").strip())
                client.close()
                client = self.ssh_client(ip, 8)
                blob, berr, bcode = self.command_bytes(client, f"cat {shlex.quote(remote)}", 120)
                if bcode != 0:
                    raise RuntimeError((berr or f"čtení archivu exit {bcode}").strip())
                local.write_bytes(blob)
                try:
                    self.command(client, f"rm -f {shlex.quote(remote)}", 10)
                except Exception:
                    pass
                if not local.exists() or local.stat().st_size < 100:
                    raise RuntimeError("Stažený archiv je prázdný nebo neúplný")
                if local.read_bytes()[:2] != b"\x1f\x8b":
                    raise RuntimeError("Stažený soubor není platný gzip archiv")
                try:
                    with tarfile.open(local, "r:gz") as tf:
                        if not tf.getmembers():
                            raise RuntimeError("Archiv neobsahuje žádné soubory")
                except tarfile.TarError as exc:
                    raise RuntimeError(f"Neplatný OpenWrt archiv: {exc}") from exc
                success += 1
                manifest["files"].append({"ip": ip, "name": name, "file": filename, "size": local.stat().st_size, "ok": True})
                self.operation.update(ip=ip, state="HOTOVO", detail=filename, log=f"{name}: {filename} uložen ({local.stat().st_size} B)")
            except Exception as exc:
                manifest["files"].append({"ip": ip, "name": name, "file": filename, "ok": False, "error": str(exc)})
                self.operation.update(ip=ip, state="CHYBA", detail=str(exc), log=f"{name}: CHYBA – {exc}")
            finally:
                if client:
                    client.close()
            self.operation.update(percent=int((i + 1) * 100 / total))
        (set_dir / "backup_info.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        self.operation.finish(f"Záloha dokončena: {success}/{total} uzlů")

    def list_backups(self) -> List[Dict[str, Any]]:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        result: List[Dict[str, Any]] = []
        for d in sorted([p for p in BACKUP_DIR.iterdir() if p.is_dir()], reverse=True):
            info_file = d / "backup_info.json"
            info: Dict[str, Any] = {}
            if info_file.exists():
                try: info = json.loads(info_file.read_text(encoding="utf-8"))
                except Exception: info = {}
            files = []
            for f in sorted(d.glob("*.tar.gz")):
                files.append({"name": f.name, "size": f.stat().st_size})
            created = info.get("created") or d.name.replace("_", " ")
            result.append({"id": d.name, "created": created, "count": len(files), "files": files})
        return result

    def _backup_set_dir(self, set_id: str) -> Optional[Path]:
        # Starší verze používaly i názvy jako "BACKUP 2026-...".
        # Povolíme libovolný přímý název pod /data/backups, ale nikdy cestu ven z adresáře.
        if not set_id or set_id in {".", ".."} or Path(set_id).name != set_id:
            return None
        d = (BACKUP_DIR / set_id).resolve()
        if d.parent != BACKUP_DIR.resolve():
            return None
        return d

    def backup_file(self, set_id: str, filename: str) -> Optional[Path]:
        if filename not in {r.get("backup_name") for r in self.routers}:
            return None
        base = self._backup_set_dir(set_id)
        if not base:
            return None
        p = (base / filename).resolve()
        if base not in p.parents or not p.is_file():
            return None
        return p

    def build_backup_zip(self, set_id: str) -> Optional[Path]:
        d = self._backup_set_dir(set_id)
        if not d or not d.is_dir():
            return None
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", set_id).strip("_") or "backup"
        zip_path = DATA_DIR / f"BACKUP_{safe_id}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for f in sorted(d.rglob("*")):
                if f.is_file():
                    z.write(f, arcname=str(f.relative_to(d)))
        return zip_path

    def delete_backup(self, set_id: str) -> bool:
        d = self._backup_set_dir(set_id)
        if not d or not d.exists():
            return False
        try:
            # Staré sady mohly obsahovat podadresáře; proto je odstranění rekurzivní.
            if d.is_dir():
                shutil.rmtree(d)
            else:
                d.unlink()
            # Odstraň i případný dříve vytvořený ZIP této sady.
            safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", set_id).strip("_") or "backup"
            for z in {DATA_DIR / f"BACKUP_{set_id}.zip", DATA_DIR / f"BACKUP_{safe_id}.zip"}:
                try:
                    if z.is_file(): z.unlink()
                except Exception:
                    pass
            return True
        except Exception:
            return False


controller = MeshController()

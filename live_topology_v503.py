from __future__ import annotations

import copy
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import paramiko
from flask import jsonify

VERSION = "6.0.3"
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
NODE_FAILURE_GRACE = max(1, int(os.environ.get("MESH_NODE_FAILURE_GRACE", "2")))

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


def _band_from_freq(freq: Any) -> str:
    try:
        value = int(freq)
    except (TypeError, ValueError):
        return "?"
    if 2400 <= value < 3000:
        return "2.4"
    if 4900 <= value < 5925:
        return "5"
    if value >= 5925:
        return "6"
    return "?"


def _iface_band(info: str) -> str:
    m = re.search(r"channel\s+\d+\s+\((\d+)\s+MHz\)", info, re.I)
    if not m:
        return "?"
    return _band_from_freq(m.group(1))


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
                "_wifi_bss_samples": {},
                "error": "čekám na první vzorek",
                "updated_at": "",
            }
            for ip, name in ROUTERS
        }
        self.links: List[Dict[str, Any]] = []
        self.updated_at = ""
        self.last_duration_ms = 0
        self._health_cache: Dict[str, Dict[str, Any]] = {}
        self._node_failures: Dict[str, int] = {ip: 0 for ip, _name in ROUTERS}
        self._host_cpu_prev: Optional[Tuple[int, int]] = None
        self.ihost: Dict[str, Any] = {
            "cpu_percent": None,
            "ram_percent": None,
            "temp_c": None,
            "updated_at": "",
        }

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

# Klienti AP: hostapd ubus je autoritativní zdroj aktuálně asociovaných STA.
# DŮLEŽITÉ: chyba ubus dotazu nesmí vypadat jako platný prázdný seznam klientů.
for OBJ in $(ubus list 'hostapd.*' 2>/dev/null || true); do
  IF="${OBJ#hostapd.}"
  FREQ="$(iw dev "$IF" info 2>/dev/null | awk '/channel/ {gsub(/[()]/, "", $3); print $3; exit}')"
  printf '__HOSTAPD_BEGIN__ %s\n' "$OBJ"
  printf '__HOSTAPD_IFACE__ %s\n' "$IF"
  printf '__HOSTAPD_FREQ__ %s\n' "$FREQ"
  if DATA="$(ubus call "$OBJ" get_clients 2>/dev/null)"; then
    printf '__HOSTAPD_OK__\n%s\n' "$DATA"
  else
    printf '__HOSTAPD_ERROR__\n'
  fi
  printf '__HOSTAPD_END__\n'
done

# iw se dál používá pro mesh peer RSSI/bitrate a jako fallback pro klienty.
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

        # v6.0.3: klientský stav vedeme po jednotlivých hostapd BSS.
        # Úspěšný BSS se může okamžitě změnit, i když jiný BSS na témže routeru
        # v daném vzorku selže. Chyba jednoho AP tak nezmrazí celý router/pásmo.
        wifi24: set[str] = set()
        wifi5: set[str] = set()
        hostapd_objects = 0
        hostapd_valid = 0
        hostapd_failed = 0
        bss_samples: Dict[str, Dict[str, Any]] = {}
        iface_by_name = {str(row.get("ifname") or ""): row for row in ifaces}

        for hm in re.finditer(r"__HOSTAPD_BEGIN__\s+(\S+)\n(.*?)__HOSTAPD_END__", out, re.S):
            hostapd_objects += 1
            obj = hm.group(1)
            body = hm.group(2)
            iface_m = re.search(r"(?m)^__HOSTAPD_IFACE__\s+(\S+)\s*$", body)
            freq_m = re.search(r"(?m)^__HOSTAPD_FREQ__\s*(\d*)\s*$", body)
            ifname = iface_m.group(1) if iface_m else (obj.split("hostapd.", 1)[1] if obj.startswith("hostapd.") else "")
            freq_hint = int(freq_m.group(1)) if freq_m and freq_m.group(1) else 0
            band = _band_from_freq(freq_hint)
            if band == "?":
                band = str((iface_by_name.get(ifname) or {}).get("band") or "?")
            fallback_macs = sorted(
                str(row.get("mac") or "").lower()
                for row in ((iface_by_name.get(ifname) or {}).get("stations") or [])
                if MAC_RE.match(str(row.get("mac") or "").lower())
            )
            sample: Dict[str, Any] = {
                "object": obj,
                "ifname": ifname,
                "band": band,
                "ok": False,
                "macs": [],
                "fallback_macs": fallback_macs,
                "source": "hostapd-error",
            }

            ok_marker = re.search(r"(?m)^__HOSTAPD_OK__\s*$", body)
            if ok_marker:
                json_text = body[ok_marker.end():].strip()
                try:
                    payload = json.loads(json_text)
                except json.JSONDecodeError:
                    payload = None
                if isinstance(payload, dict) and isinstance(payload.get("clients"), dict):
                    payload_band = _band_from_freq(payload.get("freq") or freq_hint)
                    if payload_band != "?":
                        sample["band"] = payload_band
                    macs: set[str] = set()
                    for mac, info in payload["clients"].items():
                        mac_s = str(mac).lower()
                        if not MAC_RE.match(mac_s):
                            continue
                        if isinstance(info, dict) and info.get("assoc") is False:
                            continue
                        macs.add(mac_s)
                    if sample["band"] in {"2.4", "5", "6"}:
                        sample["ok"] = True
                        sample["macs"] = sorted(macs)
                        sample["source"] = "hostapd"
                        hostapd_valid += 1
                    else:
                        hostapd_failed += 1
                else:
                    hostapd_failed += 1
            else:
                hostapd_failed += 1

            bss_samples[obj] = sample

        # Pokud `ubus list hostapd.*` některý AP objekt v tomto jediném vzorku
        # vůbec nevrátí, vytvoříme pro něj neplatný BSS vzorek podle `iw dev`.
        # sample() pak použije cache právě tohoto BSS, nikoli celého routeru.
        for iface in ifaces:
            if iface.get("type") != "ap":
                continue
            ifname = str(iface.get("ifname") or "")
            obj = f"hostapd.{ifname}"
            if obj in bss_samples:
                continue
            fallback_macs = sorted(
                str(row.get("mac") or "").lower()
                for row in (iface.get("stations") or [])
                if MAC_RE.match(str(row.get("mac") or "").lower())
            )
            bss_samples[obj] = {
                "object": obj,
                "ifname": ifname,
                "band": str(iface.get("band") or "?"),
                "ok": False,
                "macs": [],
                "fallback_macs": fallback_macs,
                "source": "hostapd-missing",
            }
            hostapd_failed += 1

        mesh_ifaces: List[Dict[str, str]] = []
        mesh_peers: List[Dict[str, Any]] = []
        wireless_ifnames = {row["ifname"] for row in ifaces}

        for iface in ifaces:
            typ = iface["type"]
            stations = iface["stations"]
            if typ == "ap":
                pass
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
            "_wifi_bss_samples": bss_samples,
            "_wifi_sample_ok": hostapd_failed == 0 and bool(bss_samples),
            "_hostapd_objects": hostapd_objects,
            "_hostapd_valid": hostapd_valid,
            "_hostapd_failed": hostapd_failed,
            "error": "",
            "updated_at": _now_text(),
            "stale": False,
            "_sample_ok": True,
        }

    def _read_ihost_stats(self) -> Dict[str, Any]:
        """Lokální iHost statistiky; žádné SSH a žádný zápis na SD."""
        cpu_percent: Optional[int] = None
        ram_percent: Optional[int] = None
        temp_c: Optional[int] = None

        try:
            first = Path("/proc/stat").read_text(encoding="utf-8", errors="replace").splitlines()[0]
            fields = [int(x) for x in first.split()[1:]]
            if len(fields) >= 4:
                total = sum(fields)
                idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
                prev = self._host_cpu_prev
                self._host_cpu_prev = (total, idle)
                if prev is not None:
                    delta_total = total - prev[0]
                    delta_idle = idle - prev[1]
                    if delta_total > 0:
                        cpu_percent = max(0, min(100, round(100.0 * (delta_total - delta_idle) / delta_total)))
        except Exception:
            pass

        try:
            mem: Dict[str, int] = {}
            for line in Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace").splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                m = re.search(r"(\d+)", value)
                if m:
                    mem[key] = int(m.group(1))
            total_kb = mem.get("MemTotal", 0)
            avail_kb = mem.get("MemAvailable", mem.get("MemFree", 0))
            if total_kb > 0:
                ram_percent = max(0, min(100, round(100.0 * (total_kb - avail_kb) / total_kb)))
        except Exception:
            pass

        # U iHostu bereme nejvyšší platnou SoC/thermal teplotu. Některé Docker
        # konfigurace /sys/class/thermal nezpřístupní; pak UI zobrazí pomlčku.
        temps: List[int] = []
        try:
            candidates = list(Path("/sys/class/thermal").glob("thermal_zone*/temp"))
            candidates += list(Path("/sys/class/hwmon").glob("hwmon*/temp*_input"))
            for path in candidates:
                try:
                    raw = int(path.read_text(encoding="utf-8", errors="replace").strip())
                    value = round(raw / 1000) if abs(raw) > 1000 else raw
                    if 0 < value < 150:
                        temps.append(value)
                except Exception:
                    continue
            if temps:
                temp_c = max(temps)
        except Exception:
            pass

        return {
            "cpu_percent": cpu_percent,
            "ram_percent": ram_percent,
            "temp_c": temp_c,
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
                    self._node_failures[ip] = 0
                except Exception as exc:
                    self._node_failures[ip] = self._node_failures.get(ip, 0) + 1
                    old = copy.deepcopy(self.nodes.get(ip, {}))
                    # Dva jednotlivé neúspěšné SSH vzorky ještě neprohlásí uzel
                    # za OFFLINE a nezahodí jeho poslední mesh data.
                    if old.get("online") and self._node_failures[ip] <= NODE_FAILURE_GRACE:
                        fetched[ip] = {
                            **old,
                            "ip": ip,
                            "name": name,
                            "hostname": old.get("hostname") or name,
                            "online": True,
                            "stale": True,
                            "_sample_ok": False,
                            "error": str(exc),
                        }
                    else:
                        fetched[ip] = {
                            **old,
                            "ip": ip,
                            "name": name,
                            "hostname": old.get("hostname") or name,
                            "online": False,
                            "stale": False,
                            "clients": 0,
                            "clients_24": 0,
                            "clients_5": 0,
                            "lan_clients": 0,
                            "mesh_ifaces": [],
                            "mesh_peers": [],
                            "wifi_client_macs_24": [],
                            "wifi_client_macs_5": [],
                            "lan_client_macs": [],
                            "_wifi_bss_samples": {},
                            "_sample_ok": False,
                            "error": str(exc),
                            "updated_at": _now_text(),
                        }

        # v6.0.3: hostapd fallback je PO JEDNOTLIVÝCH BSS/AP.
        # Úspěšný 5GHz BSS se tedy aktualizuje ihned i v případě, že ve stejném
        # 5s vzorku selže jiný 2.4GHz BSS (a naopak).
        for ip, node in fetched.items():
            if not node.get("online"):
                continue
            old = self.nodes.get(ip, {})
            old_bss = old.get("_wifi_bss_samples") if isinstance(old.get("_wifi_bss_samples"), dict) else {}
            current_bss = node.get("_wifi_bss_samples") if isinstance(node.get("_wifi_bss_samples"), dict) else {}
            merged_bss: Dict[str, Dict[str, Any]] = {}
            stale_bss: List[str] = []

            for key, raw_sample in current_bss.items():
                sample = copy.deepcopy(raw_sample) if isinstance(raw_sample, dict) else {}
                macs: set[str]
                if sample.get("ok"):
                    macs = {str(m).lower() for m in (sample.get("macs") or []) if MAC_RE.match(str(m).lower())}
                    sample["source"] = "hostapd"
                    sample["stale"] = False
                else:
                    previous = old_bss.get(key) if isinstance(old_bss, dict) else None
                    previous_macs = (previous or {}).get("macs") if isinstance(previous, dict) else None
                    if previous_macs is not None:
                        macs = {str(m).lower() for m in previous_macs if MAC_RE.match(str(m).lower())}
                        sample["source"] = "bss-cache"
                    else:
                        macs = {str(m).lower() for m in (sample.get("fallback_macs") or []) if MAC_RE.match(str(m).lower())}
                        sample["source"] = "iw-first-sample"
                    sample["stale"] = True
                    stale_bss.append(str(key))
                sample["macs"] = sorted(macs)
                sample.pop("fallback_macs", None)
                merged_bss[str(key)] = sample

            wifi24: set[str] = set()
            wifi5: set[str] = set()
            for sample in merged_bss.values():
                band = str(sample.get("band") or "?")
                macs = {str(m).lower() for m in (sample.get("macs") or []) if MAC_RE.match(str(m).lower())}
                if band == "2.4":
                    wifi24.update(macs)
                elif band == "5":
                    wifi5.update(macs)

            lan = {str(m).lower() for m in (node.get("lan_client_macs") or []) if MAC_RE.match(str(m).lower())}
            lan.difference_update(wifi24)
            lan.difference_update(wifi5)
            node["_wifi_bss_samples"] = merged_bss
            node["wifi_client_macs_24"] = sorted(wifi24)
            node["wifi_client_macs_5"] = sorted(wifi5)
            node["lan_client_macs"] = sorted(lan)
            node["clients_24"] = len(wifi24)
            node["clients_5"] = len(wifi5)
            node["lan_clients"] = len(lan)
            node["clients"] = len(wifi24 | wifi5 | lan)
            node["wifi_stale"] = bool(stale_bss)
            node["wifi_stale_bss"] = stale_bss

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

        ihost = self._read_ihost_stats()
        with self.lock:
            links = self._build_links(fetched)
            self.nodes = fetched
            self.links = links
            self.ihost = ihost
            self.sequence += 1
            self.updated_at = _now_text()
            self.last_duration_ms = int((time.monotonic() - started) * 1000)

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            nodes = copy.deepcopy(self.nodes)
            links = copy.deepcopy(self.links)
            online = sum(1 for node in nodes.values() if node.get("online"))

            # 2.4 GHz, 5 GHz i CELKEM jsou ze stejného právě načteného
            # živého vzorku. Deduplication je podle MAC napříč všemi uzly.
            live_mac24: set[str] = set()
            live_mac5: set[str] = set()
            live_lan: set[str] = set()
            for node in nodes.values():
                if not node.get("online"):
                    continue
                live_mac24.update(str(m).lower() for m in (node.get("wifi_client_macs_24") or []))
                live_mac5.update(str(m).lower() for m in (node.get("wifi_client_macs_5") or []))
                live_lan.update(str(m).lower() for m in (node.get("lan_client_macs") or []))

            live_clients = live_mac24 | live_mac5 | live_lan

            public_nodes = []
            for ip, _name in ROUTERS:
                n = copy.deepcopy(nodes[ip])
                # Interní seznamy MAC nejsou potřeba v browseru.
                for key in ("mesh_ifaces", "mesh_peers", "wifi_client_macs_24", "wifi_client_macs_5", "lan_client_macs", "_wifi_bss_samples", "_sample_ok", "_wifi_sample_ok", "_hostapd_objects", "_hostapd_valid", "_hostapd_failed"):
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
                "ihost": copy.deepcopy(self.ihost),
                "summary": {
                    "online_routers": online,
                    "router_count": len(ROUTERS),
                    "mesh_links": len(links),
                    "clients": len(live_clients),
                    "clients_24": len(live_mac24),
                    "clients_5": len(live_mac5),
                    "lan_clients": len(live_lan),
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

from __future__ import annotations

import json
import os
import re
import shlex
import threading
import time
import zipfile
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

    def refresh_snapshot(self) -> Dict[str, Any]:
        node_states: List[Dict[str, Any]] = []
        raw_nodes: Dict[str, Dict[str, Any]] = {}
        mac_to_ip: Dict[str, str] = {}
        clients: List[Dict[str, str]] = []

        for router in self.routers:
            ip = router["ip"]
            state = NodeState(ip=ip, name=router["name"])
            data: Dict[str, Any] = {"mesh_peers": [], "freqs": {}, "local_macs": []}
            client = None
            try:
                client = self.ssh_client(ip, 4)
                cmd = r'''printf 'HOST='; hostname 2>/dev/null || true
printf 'UP='; cut -d. -f1 /proc/uptime 2>/dev/null || true
printf 'MACS='; for f in /sys/class/net/*/address; do cat "$f" 2>/dev/null; done | tr '\n' ' '; echo
printf 'WIRELESS_BEGIN\n'; ubus call network.wireless status 2>/dev/null || true; printf '\nWIRELESS_END\n'
printf 'IW_BEGIN\n'; iw dev 2>/dev/null || true; printf '\nIW_END\n'
printf 'NEIGH_BEGIN\n'; ip neigh show dev br-lan 2>/dev/null || true; printf '\nNEIGH_END\n'
'''
                out, err, code = self.command(client, cmd, 15)
                state.online = True
                host = re.search(r"^HOST=(.*)$", out, re.M)
                up = re.search(r"^UP=(.*)$", out, re.M)
                macs = re.search(r"^MACS=(.*)$", out, re.M)
                state.hostname = host.group(1).strip() if host else ""
                if up and up.group(1).strip().isdigit():
                    sec = int(up.group(1).strip())
                    state.uptime = f"{sec // 86400}d {(sec % 86400) // 3600}h"
                if macs:
                    data["local_macs"] = [m.lower() for m in MAC_RE.findall(macs.group(1))]
                    for m in data["local_macs"]:
                        mac_to_ip[m] = ip

                w = re.search(r"WIRELESS_BEGIN\n(.*?)\nWIRELESS_END", out, re.S)
                wireless_json = {}
                if w:
                    try:
                        wireless_json = json.loads(w.group(1).strip() or "{}")
                    except Exception:
                        wireless_json = {}
                iw_match = re.search(r"IW_BEGIN\n(.*?)\nIW_END", out, re.S)
                iw_text = iw_match.group(1) if iw_match else ""
                iface_blocks = re.split(r"\n\s*Interface\s+", "\n" + iw_text)
                mesh_ifaces: List[str] = []
                for block in iface_blocks[1:]:
                    lines = block.strip().splitlines()
                    if not lines:
                        continue
                    ifname = lines[0].strip()
                    body = "\n".join(lines[1:])
                    if re.search(r"\btype\s+mesh point\b", body):
                        mesh_ifaces.append(ifname)
                    freq = re.search(r"\bchannel\s+\d+\s+\((\d+)\s+MHz\)", body)
                    if freq:
                        data["freqs"][ifname] = int(freq.group(1))

                # fallback detect mesh interfaces from ubus
                for radio_data in wireless_json.values() if isinstance(wireless_json, dict) else []:
                    if not isinstance(radio_data, dict):
                        continue
                    for iface in radio_data.get("interfaces", []) or []:
                        cfg = iface.get("config", {}) or {}
                        if str(cfg.get("mode", "")).lower() == "mesh":
                            ifname = str(iface.get("ifname", "")).strip()
                            if ifname and ifname not in mesh_ifaces:
                                mesh_ifaces.append(ifname)

                for ifname in mesh_ifaces:
                    safe_if = shlex.quote(ifname)
                    peer_out, _, _ = self.command(client, f"iw dev {safe_if} station dump 2>/dev/null || true", 8)
                    current: Optional[Dict[str, Any]] = None
                    for line in peer_out.splitlines():
                        m = re.match(r"^Station\s+([0-9a-f:]{17})", line.strip(), re.I)
                        if m:
                            if current:
                                data["mesh_peers"].append(current)
                            current = {"mac": m.group(1).lower(), "signal": None, "speed": "", "freq": data["freqs"].get(ifname), "ifname": ifname}
                            continue
                        if not current:
                            continue
                        s = re.match(r"^signal:\s*(-?\d+)", line.strip())
                        if s:
                            current["signal"] = int(s.group(1))
                        t = re.match(r"^tx bitrate:\s*([0-9.]+)\s*MBit/s", line.strip(), re.I)
                        if t:
                            current["speed"] = f"{t.group(1)} Mbit/s"
                    if current:
                        data["mesh_peers"].append(current)

                neigh_match = re.search(r"NEIGH_BEGIN\n(.*?)\nNEIGH_END", out, re.S)
                neigh_text = neigh_match.group(1) if neigh_match else ""
                for line in neigh_text.splitlines():
                    m = re.search(r"^(\S+)\s+dev\s+br-lan.*?lladdr\s+([0-9a-f:]{17})\s+(\S+)", line, re.I)
                    if m and m.group(3).upper() not in {"FAILED", "INCOMPLETE"}:
                        clients.append({"node": router["name"], "node_ip": ip, "ip": m.group(1), "mac": m.group(2).lower(), "type": "LAN/Wi-Fi"})
                state.clients = sum(1 for c in clients if c["node_ip"] == ip)
            except Exception as exc:
                state.error = str(exc)
            finally:
                if client:
                    client.close()
            raw_nodes[ip] = data
            node_states.append(asdict(state))

        links_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for source_ip, data in raw_nodes.items():
            for peer in data.get("mesh_peers", []):
                target_ip = mac_to_ip.get(peer.get("mac", ""))
                if not target_ip or target_ip == source_ip:
                    continue
                key = tuple(sorted((source_ip, target_ip)))
                link = links_by_key.setdefault(key, {
                    "a": key[0], "b": key[1], "signals": [], "speeds": [], "freqs": []
                })
                if peer.get("signal") is not None:
                    link["signals"].append(peer["signal"])
                if peer.get("speed"):
                    try:
                        link["speeds"].append(float(str(peer["speed"]).split()[0]))
                    except Exception:
                        pass
                if peer.get("freq"):
                    link["freqs"].append(int(peer["freq"]))

        links: List[Dict[str, Any]] = []
        for link in links_by_key.values():
            signal = round(sum(link["signals"]) / len(link["signals"])) if link["signals"] else None
            speed = max(link["speeds"]) if link["speeds"] else None
            freq = round(sum(link["freqs"]) / len(link["freqs"])) if link["freqs"] else None
            links.append({"a": link["a"], "b": link["b"], "dbm": signal, "speed_mbps": speed, "mhz": freq})

        snapshot = {"nodes": node_states, "links": links, "clients": clients, "updated": time.time()}
        with self._status_lock:
            self._snapshot = snapshot
        return snapshot

    def _run_per_router(self, title: str, worker: Callable[[Dict[str, str]], Tuple[bool, str]], result_label: str) -> None:
        if not self.operation.start(title, self.routers):
            return
        ok_count = 0
        total = len(self.routers)
        for index, router in enumerate(self.routers):
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
        threading.Thread(target=self._run_per_router, args=("Aktualizace všech routerů", worker, "Aktualizace"), daemon=True).start()
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
        routers = self.routers if target == "all" else [r for r in self.routers if r["ip"] == target]
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

    def start_backup(self) -> bool:
        if self.operation.snapshot()["running"]:
            return False
        threading.Thread(target=self._backup_worker, daemon=True).start()
        return True

    def _backup_worker(self) -> None:
        if not self.operation.start("Záloha konfigurace OpenWrt", self.routers):
            return
        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        set_dir = BACKUP_DIR / timestamp
        set_dir.mkdir(parents=True, exist_ok=True)
        total = len(self.routers)
        success = 0
        manifest = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "files": []}
        for i, router in enumerate(self.routers):
            ip, name = router["ip"], router["name"]
            filename = router.get("backup_name") or f"{name}.tar.gz"
            remote = f"/tmp/{filename}"
            local = set_dir / filename
            self.operation.update(percent=int(i * 100 / total), current=f"Zálohuji {name} ({ip})…", ip=ip, state="PROBÍHÁ", log=f"{name}: vytvářím standardní sysupgrade archiv")
            client = None
            try:
                client = self.ssh_client(ip, 7)
                out, err, code = self.command(client, f"umask 077; rm -f {shlex.quote(remote)}; sysupgrade -b {shlex.quote(remote)}; test -s {shlex.quote(remote)}", 120)
                if code != 0:
                    raise RuntimeError((err or out or f"sysupgrade exit {code}").strip())
                sftp = client.open_sftp()
                try:
                    sftp.get(remote, str(local))
                finally:
                    sftp.close()
                self.command(client, f"rm -f {shlex.quote(remote)}", 10)
                if not local.exists() or local.stat().st_size < 100:
                    raise RuntimeError("Stažený archiv je prázdný nebo neúplný")
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

    def backup_file(self, set_id: str, filename: str) -> Optional[Path]:
        if not re.fullmatch(r"[0-9_-]+", set_id):
            return None
        if filename not in {r.get("backup_name") for r in self.routers}:
            return None
        p = (BACKUP_DIR / set_id / filename).resolve()
        base = (BACKUP_DIR / set_id).resolve()
        if base not in p.parents or not p.is_file():
            return None
        return p

    def build_backup_zip(self, set_id: str) -> Optional[Path]:
        if not re.fullmatch(r"[0-9_-]+", set_id):
            return None
        d = (BACKUP_DIR / set_id).resolve()
        if not d.is_dir() or BACKUP_DIR.resolve() not in d.parents:
            return None
        zip_path = DATA_DIR / f"BACKUP_{set_id}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for f in sorted(d.iterdir()):
                if f.is_file():
                    z.write(f, arcname=f.name)
        return zip_path

    def delete_backup(self, set_id: str) -> bool:
        if not re.fullmatch(r"[0-9_-]+", set_id):
            return False
        d = (BACKUP_DIR / set_id).resolve()
        if not d.is_dir() or BACKUP_DIR.resolve() not in d.parents:
            return False
        for p in d.iterdir():
            if p.is_file(): p.unlink()
        d.rmdir()
        return True


controller = MeshController()

from __future__ import annotations

import json
import os
import re
import shlex
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import jsonify, request

from mesh_core import controller

VERSION = "7.0.2"
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
STATE_FILE = DATA_DIR / "lan_port_state.json"
WATCH_SECONDS = max(15, int(os.environ.get("MESH_LAN_PORT_WATCH_SECONDS", "15")))
PROTECT_SCAN_SECONDS = max(30, int(os.environ.get("MESH_LAN_PROTECT_SCAN_SECONDS", "60")))
REASSERT_SECONDS = max(60, int(os.environ.get("MESH_LAN_REASSERT_SECONDS", "300")))
ACTION_RETRY_SECONDS = max(30, int(os.environ.get("MESH_LAN_ACTION_RETRY_SECONDS", "60")))
PORT_RE = re.compile(r"^lan([1-4])$", re.I)

PROTECTED_HOSTS: Dict[str, Dict[str, str]] = {
    "ihost": {"name": "iHOST", "ip": "192.168.30.186"},
    "homeassistant": {"name": "Home Assistant", "ip": "192.168.30.223"},
}


def _empty_state() -> Dict[str, Any]:
    return {
        "version": VERSION,
        "blocked": {},
        "protected_hosts": {
            key: {**value, "last_node": "", "last_port": "", "updated": 0}
            for key, value in PROTECTED_HOSTS.items()
        },
    }


class LanPortController:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.state = self._load_state()
        self.last_errors: Dict[str, str] = {}
        self.last_scan = 0.0
        self.app = None
        self._last_reassert: Dict[str, float] = {}

    def _load_state(self) -> Dict[str, Any]:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        state = _empty_state()
        try:
            raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                blocked = raw.get("blocked")
                if isinstance(blocked, dict):
                    for ip, ports in blocked.items():
                        if isinstance(ports, list):
                            clean = sorted({str(p).lower() for p in ports if PORT_RE.fullmatch(str(p))})
                            if clean:
                                state["blocked"][str(ip)] = clean
                old_protected = raw.get("protected_hosts")
                if isinstance(old_protected, dict):
                    for key, base in state["protected_hosts"].items():
                        old = old_protected.get(key)
                        if isinstance(old, dict):
                            base["last_node"] = str(old.get("last_node") or "")
                            port = str(old.get("last_port") or "").lower()
                            base["last_port"] = port if PORT_RE.fullmatch(port) else ""
                            try:
                                base["updated"] = int(old.get("updated") or 0)
                            except (TypeError, ValueError):
                                base["updated"] = 0
        except Exception:
            pass
        return state

    def _save_state(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)

    def start(self) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._loop, name="lan-port-v620", daemon=True)
            self.thread.start()

    @staticmethod
    def _router_ips() -> set[str]:
        return {str(r.get("ip") or "") for r in controller.routers}

    def _validate(self, ip: str, port: str) -> Tuple[str, str]:
        ip = str(ip or "").strip()
        port = str(port or "").strip().lower()
        if ip not in self._router_ips():
            raise ValueError("Neznámý router")
        if not PORT_RE.fullmatch(port):
            raise ValueError("Neplatný LAN port")
        return ip, port

    def _is_protected_locked(self, ip: str, port: str) -> List[str]:
        names: List[str] = []
        for info in self.state.get("protected_hosts", {}).values():
            if info.get("last_node") == ip and info.get("last_port") == port:
                names.append(str(info.get("name") or info.get("ip") or "chráněné zařízení"))
        return names

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            protected_ports: Dict[str, Dict[str, List[str]]] = {}
            for info in self.state.get("protected_hosts", {}).values():
                ip = str(info.get("last_node") or "")
                port = str(info.get("last_port") or "")
                if ip and port:
                    protected_ports.setdefault(ip, {}).setdefault(port, []).append(str(info.get("name") or ""))
            return {
                "ok": True,
                "version": VERSION,
                "blocked": json.loads(json.dumps(self.state.get("blocked", {}))),
                "protected": protected_ports,
                "protected_hosts": json.loads(json.dumps(self.state.get("protected_hosts", {}))),
                "errors": dict(self.last_errors),
                "state_file": str(STATE_FILE),
                "watch_seconds": WATCH_SECONDS,
            }

    def _set_link(self, ip: str, port: str, blocked: bool) -> Tuple[bool, str]:
        client = None
        try:
            client = controller.ssh_client(ip, timeout=5)
            quoted = shlex.quote(port)
            desired = "down" if blocked else "up"
            command = (
                f"test -e /sys/class/net/{quoted} && "
                f"ip link set dev {quoted} {desired} && "
                f"printf 'OK:%s\\n' {shlex.quote(desired)}"
            )
            out, err, code = controller.command(client, command, timeout=10)
            if code != 0:
                return False, (err or out).strip() or f"SSH rc={code}"
            return True, out.strip() or "OK"
        except Exception as exc:
            return False, str(exc)
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    def set_blocked(self, ip: str, port: str, blocked: bool) -> Dict[str, Any]:
        ip, port = self._validate(ip, port)

        # Před blokací udělej čerstvou kontrolu tohoto routeru. Tím se ochrana
        # iHost/HA neopírá jen o poslední periodický scan.
        if blocked:
            self._scan_router_protection(ip)

        with self.lock:
            protected = self._is_protected_locked(ip, port)
            if blocked and protected:
                return {
                    "ok": False,
                    "protected": True,
                    "error": "Port je chráněný: " + ", ".join(protected),
                    "devices": protected,
                }

        ok, detail = self._set_link(ip, port, blocked)
        if not ok:
            with self.lock:
                self.last_errors[f"{ip}/{port}"] = detail
            return {"ok": False, "error": detail}

        with self.lock:
            ports = set(self.state.setdefault("blocked", {}).get(ip, []))
            if blocked:
                ports.add(port)
            else:
                ports.discard(port)
            if ports:
                self.state["blocked"][ip] = sorted(ports)
            else:
                self.state["blocked"].pop(ip, None)
            self.last_errors.pop(f"{ip}/{port}", None)
            self._save_state()
        return {"ok": True, "ip": ip, "port": port, "blocked": bool(blocked)}

    def _scan_router_protection(self, ip: str) -> bool:
        client = None
        hosts = " ".join(shlex.quote(v["ip"]) for v in PROTECTED_HOSTS.values())
        script = f'''set -u
for H in {hosts}; do
  LINE="$(ip -4 neigh show "$H" dev br-lan 2>/dev/null | head -n1)"
  MAC="$(printf '%s\\n' "$LINE" | sed -n 's/.* lladdr \\([0-9A-Fa-f:]\\{{17\\}}\\).*/\\1/p')"
  [ -n "$MAC" ] || continue
  if command -v bridge >/dev/null 2>&1; then
    bridge fdb show 2>/dev/null | awk -v h="$H" -v m="$MAC" '
      tolower($1)==tolower(m) && $2=="dev" && $3 ~ /^lan[1-4]$/ {{print "PROTECTED=" h "|" tolower(m) "|" $3; exit}}'
  fi
done
'''
        try:
            client = controller.ssh_client(ip, timeout=5)
            out, _err, code = controller.script(client, script, timeout=12)
            if code != 0:
                return False
        except Exception:
            return False
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

        found: Dict[str, str] = {}
        for line in out.splitlines():
            if not line.startswith("PROTECTED="):
                continue
            parts = line.split("=", 1)[1].split("|")
            if len(parts) != 3:
                continue
            host_ip, _mac, port = parts
            port = port.lower()
            if PORT_RE.fullmatch(port):
                found[host_ip] = port

        changed = False
        unblock: List[Tuple[str, str]] = []
        now = int(time.time())
        with self.lock:
            for key, base in PROTECTED_HOSTS.items():
                host_ip = base["ip"]
                port = found.get(host_ip)
                if not port:
                    continue
                entry = self.state["protected_hosts"][key]
                if entry.get("last_node") != ip or entry.get("last_port") != port:
                    entry["last_node"] = ip
                    entry["last_port"] = port
                    entry["updated"] = now
                    changed = True
                blocked_ports = set(self.state.get("blocked", {}).get(ip, []))
                if port in blocked_ports:
                    blocked_ports.discard(port)
                    if blocked_ports:
                        self.state["blocked"][ip] = sorted(blocked_ports)
                    else:
                        self.state["blocked"].pop(ip, None)
                    unblock.append((ip, port))
                    changed = True
            if changed:
                self._save_state()

        # Chráněný host má vždy přednost před uloženou blokací.
        for node_ip, port in unblock:
            self._set_link(node_ip, port, False)
        return True

    def scan_protected_hosts(self) -> None:
        for router in list(controller.routers):
            ip = str(router.get("ip") or "")
            if ip:
                self._scan_router_protection(ip)
        self.last_scan = time.monotonic()

    def _live_port_up(self, ip: str, port: str) -> Optional[bool]:
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

    def _loop(self) -> None:
        # Nech síť po startu Dockeru krátce ustálit.
        self.stop_event.wait(5)
        while not self.stop_event.is_set():
            try:
                if time.monotonic() - self.last_scan >= PROTECT_SCAN_SECONDS:
                    self.scan_protected_hosts()
                self.enforce()
            except Exception:
                pass
            self.stop_event.wait(WATCH_SECONDS)


lan_port_controller = LanPortController()


def init_lan_port_control_v620(app: Any) -> LanPortController:
    endpoint_state = "v620_lan_port_state"
    endpoint_set = "v620_lan_port_set"

    if endpoint_state not in app.view_functions:
        @app.get("/api/v620/lan-ports", endpoint=endpoint_state)
        def _state():
            return jsonify(lan_port_controller.snapshot())

    if endpoint_set not in app.view_functions:
        @app.post("/api/v620/lan-ports", endpoint=endpoint_set)
        def _set():
            payload = request.get_json(silent=True) or {}
            try:
                result = lan_port_controller.set_blocked(
                    str(payload.get("ip") or ""),
                    str(payload.get("port") or ""),
                    bool(payload.get("blocked")),
                )
            except ValueError as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400
            return jsonify(result), (200 if result.get("ok") else 409)
    lan_port_controller.app = app
    lan_port_controller.start()
    return lan_port_controller
